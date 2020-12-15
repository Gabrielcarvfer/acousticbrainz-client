# Copyright 2014 Music Technology Group - Universitat Pompeu Fabra
# Copyright 2020 Gabriel Ferreira (@gabrielcarvfer)
# acousticbrainz-client is available under the terms of the GNU
# General Public License, version 3 or higher. See COPYING for more details.
import json
import os
import shutil
import subprocess
import time
import threading
import uuid

try:
    import requests
except ImportError:
    from .vendor import requests


from abz import compat


def is_valid_uuid(u):
    try:
        u = uuid.UUID(u)
        return True
    except ValueError:
        return False


def run_extractor(essentia_path, input_path, output_path):
    extractor = essentia_path
    args = [extractor, input_path, output_path]

    with subprocess.Popen(args, stderr=subprocess.STDOUT, stdout=subprocess.PIPE) as p:
        (out, err) = p.communicate()
        retcode = p.returncode
        return retcode, out.decode("utf-8")


def submit_features(host, recordingid, features, api_lock, api_request_delay):
    with api_lock:
        time.sleep(api_request_delay)

    featstr = json.dumps(features)
    url = compat.urlunparse(('https', host, '/%s/low-level' % recordingid, '', '', ''))
    r = requests.post(url, data=featstr)
    r.raise_for_status()


def duplicated_features(acoustid_server_address, musicbrainz_trackid, essentia_version, api_lock, api_request_delay):
    with api_lock:
        time.sleep(api_request_delay)

    # Check if someone already submitted the acousticbrainz features
    req = requests.get("https://"+acoustid_server_address+"/"+musicbrainz_trackid+"/low-level").json()
    is_duplicate = len(req.keys()) > 1
    if is_duplicate:
        # If we reached this point, there is an entry for this song, but it may be outdated
        if req["metadata"]["version"]["essentia_git_sha"] != essentia_version:
            # If versions do not match, extract features
            is_duplicate = False
    return is_duplicate


def process_file(shared_dict, filepath, state_queue):
    tmpname = os.path.basename(filepath)+'_.json'
    pending_tmpname = "features/pending/"+tmpname

    state_queue.put((tmpname, "pending", "", 0.0))
    pending_timestamp = time.time()

    # If features haven't been extracted yet, extract them
    if tmpname not in shared_dict["processed_files"]:
        # If we are offline, we can use mutagen to check if the recording already exists in the
        # acousticbrainz server and skip feature extraction
        if not shared_dict["offline"]:
            try:
                import mutagen
                f = mutagen.File(filepath)
                recid = str(f.tags['UFID:http://musicbrainz.org'].data.decode("utf-8"))

                # Check if track ID already exists
                duplicate = duplicated_features(shared_dict["host"],
                                                recid,
                                                shared_dict["essentia_version"],
                                                shared_dict["api_lock"],
                                                shared_dict["api_request_delay"])
                if duplicate:
                    state_queue.put((tmpname, "duplicate", "matching feature set", 0.0))
                    return
            except Exception as e:
                # Whatever, proceed to the slow path
                pass

        # The extractor doesn't seem to handle utf-8 properly, so we write to a temporary file
        thread_tmpname = str(threading.get_ident())+".json"
        retcode, out = run_extractor(shared_dict["essentia_path"], filepath, thread_tmpname)

        try:
            shutil.move(thread_tmpname, pending_tmpname)
            # Insert extractor sha for reference
            with open(pending_tmpname, "r", encoding="utf-8") as f:
                features = json.load(f)
            features["metadata"]["version"]["essentia_build_sha"] = shared_dict["essentia_build_sha"]
            with open(pending_tmpname, "w", encoding="utf-8") as f:
                json.dump(features, f, indent=3)
        except FileNotFoundError:
            extraction_timestamp = time.time()
            state_queue.put((tmpname, "failed", "extraction", extraction_timestamp-pending_timestamp))
            print()
            print(out)
            return
    else:
        retcode = 0

    extraction_timestamp = time.time()

    # If we are at this point, the features file will be at features/pending
    if retcode == 2:
        state_queue.put((tmpname, "failed", "nombid", extraction_timestamp-pending_timestamp))
        shutil.move(pending_tmpname, "features/failed/nombid/"+tmpname)
        print()
        print(out)
    elif retcode == 1:
        state_queue.put((tmpname, "failed", "extraction", extraction_timestamp-pending_timestamp))
        shutil.move(pending_tmpname, "features/failed/extraction/"+tmpname)
        print()
        print(out)
    elif retcode > 0 or retcode < 0:  # Unknown error, not 0, 1, 2
        state_queue.put((tmpname, "failed", "unknownerror", extraction_timestamp-pending_timestamp))
        shutil.move(pending_tmpname, "features/failed/unknownerror/"+tmpname)
        print()
        print(out)
    else:
        state_queue.put((tmpname, "extracted", "", extraction_timestamp-pending_timestamp))
        # Previously processed files won't get reprocessed to save up computational time and server requests
        if tmpname in shared_dict["processed_files"]:
            if shared_dict["processed_files"][tmpname][0] == "duplicate":
                state_queue.put((tmpname, "duplicate", "", extraction_timestamp-pending_timestamp))
                return

        if not shared_dict["offline"]:
            try:
                with open(pending_tmpname, "r") as f:
                    features = json.load(f)
                # Recording MBIDs are tagged with _trackid for historic reasons
                recordingids = features["metadata"]["tags"]["musicbrainz_trackid"]
                if not isinstance(recordingids, list):
                    recordingids = [recordingids]
                recs = [r for r in recordingids if is_valid_uuid(r)]
                if recs:
                    recid = recs[0]

                    # If we reached this point, the previous duplicate check
                    # was skipped due to a different build_sha/offline work
                    duplicate = duplicated_features(shared_dict["host"],
                                                    recid,
                                                    shared_dict["essentia_version"],
                                                    shared_dict["api_lock"],
                                                    shared_dict["api_request_delay"]
                                                    )

                    # Finally, submit features if not duplicates
                    if duplicate:
                        shutil.move(pending_tmpname, "features/duplicate/"+tmpname)
                        state_queue.put((tmpname, "duplicate", "", extraction_timestamp-pending_timestamp))
                    else:
                        try:
                            submit_features(shared_dict["host"],
                                            recid,
                                            features,
                                            shared_dict["api_lock"],
                                            shared_dict["api_request_delay"]
                                            )
                            submission_timestamp = time.time()
                            shutil.move(pending_tmpname, "features/success/"+tmpname)
                            state_queue.put((tmpname, "success", "", submission_timestamp-extraction_timestamp))
                        except requests.exceptions.HTTPError as e:
                            shutil.move(pending_tmpname, "features/failed/submission/"+tmpname)
                            submission_timestamp = time.time()
                            state_queue.put((tmpname, "failed", "submission", submission_timestamp-extraction_timestamp))
                            print()
                            print(e.response.text)
                else:
                    state_queue.put((tmpname, "failed", "badmbid", extraction_timestamp-pending_timestamp))
                    shutil.move(pending_tmpname, "features/failed/badmbid/"+tmpname)
            except ValueError:
                shutil.move(pending_tmpname, "features/failed/jsonerror/"+tmpname)
                state_queue.put((tmpname, "failed", "jsonerror", extraction_timestamp-pending_timestamp))
            except KeyError:
                shutil.move(pending_tmpname, "features/failed/notrackid/"+tmpname)
                state_queue.put((tmpname, "failed", "notrackid", extraction_timestamp-pending_timestamp))
            except FileNotFoundError:
                state_queue.put((tmpname, "failed", "extraction", extraction_timestamp-pending_timestamp))

