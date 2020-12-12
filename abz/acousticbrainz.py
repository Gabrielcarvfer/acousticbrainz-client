# Copyright 2014 Music Technology Group - Universitat Pompeu Fabra
# Copyright 2020 Gabriel Ferreira (@gabrielcarvfer)
# acousticbrainz-client is available under the terms of the GNU
# General Public License, version 3 or higher. See COPYING for more details.
import json
import os
import subprocess
import sys
import uuid

try:
    import requests
except ImportError:
    from .vendor import requests


from abz import compat

VERBOSE = False

RESET = "\x1b[0m"
RED = "\x1b[31m"
GREEN = "\x1b[32m"


def _update_progress(lock, msg, status="...", colour=RESET):
    with lock:
        if VERBOSE:
            sys.stdout.write("%s[%-10s]%s " % (colour, status, RESET))
            print(msg.encode("ascii", "ignore"))
        else:
            sys.stdout.write("%s[%-10s]%s " % (colour, status, RESET))
            sys.stdout.write("%s\x1b[K\r" % msg)
            sys.stdout.flush()


def _start_progress(lock, msg, status="...", colour=RESET):
    with lock:
        print()
    _update_progress(lock, msg, status, colour)


def is_valid_uuid(u):
    try:
        u = uuid.UUID(u)
        return True
    except ValueError:
        return False


def run_extractor(essentia_path, input_path, output_path):
    extractor = essentia_path
    args = [extractor, input_path, output_path]

    p = subprocess.Popen(args, stderr=subprocess.STDOUT, stdout=subprocess.PIPE)
    (out, err) = p.communicate()
    retcode = p.returncode
    return retcode, out


def submit_features(host, recordingid, features):
    featstr = json.dumps(features)
    url = compat.urlunparse(('http', host, '/%s/low-level' % recordingid, '', '', ''))
    r = requests.post(url, data=featstr)
    r.raise_for_status()


def process_file(shared_dict, filepath):
    _start_progress(shared_dict["lock"], filepath)

    tmpname = os.path.basename(filepath)+'_.json'
    if not os.path.exists(tmpname):
        retcode, out = run_extractor(shared_dict["essentia_path"], filepath, tmpname)
    else:
        retcode = 0

    if retcode == 2:
        _update_progress(shared_dict["lock"], filepath, "No MBID", RED)
        print()
        print(out)
    elif retcode == 1:
        _update_progress(shared_dict["lock"], filepath, "Failed extraction", RED)
        print()
        print(out)
    elif retcode > 0 or retcode < 0:  # Unknown error, not 0, 1, 2
        _update_progress(shared_dict["lock"], filepath, "Unknown error %s" % retcode, RED)
        print()
        print(out)
    else:
        if os.path.isfile(tmpname):
            try:
                # Insert extractor sha for reference
                with open(tmpname, "r") as f:
                    features = json.load(f)

                if "essentia_build_sha" in features["metadata"]["version"]:
                    _update_progress(shared_dict["lock"], filepath, "Sent", GREEN)
                    return

                features["metadata"]["version"]["essentia_build_sha"] = shared_dict["essentia_build_sha"]

                # Recording MBIDs are tagged with _trackid for historic reasons
                recordingids = features["metadata"]["tags"]["musicbrainz_trackid"]
                if not isinstance(recordingids, list):
                    recordingids = [recordingids]
                recs = [r for r in recordingids if is_valid_uuid(r)]
                if recs:
                    recid = recs[0]
                    try:
                        submit_features(shared_dict["host"], recid, features)
                        with open(tmpname, "w") as f:
                            json.dump(features, f, indent=3)
                        _update_progress(shared_dict["lock"], filepath, "Sent", GREEN)
                    except requests.exceptions.HTTPError as e:
                        _update_progress(shared_dict["lock"], filepath, "Error", RED)
                        print()
                        print(e.response.text)
                else:
                    _update_progress(shared_dict["lock"], filepath, "Bad MBID", RED)
            except ValueError:
                _update_progress(shared_dict["lock"], filepath, "JSON error", RED)
                pass


def scan_files_to_process(paths, supported_extensions):
    files_to_process = []
    for path in paths:
        print("Processing %s" % path)
        for dirpath, dirnames, filenames in os.walk(path):
            for f in filenames:
                if f.lower().split(".")[-1] in supported_extensions:
                    files_to_process.append(os.path.abspath(os.path.join(dirpath, f)))
    return files_to_process

