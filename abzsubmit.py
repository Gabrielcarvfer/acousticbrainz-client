#!/usr/bin/env python

# Client for submitting feature files to the AcousticBrainz project

# Copyright 2014 Music Technology Group - Universitat Pompeu Fabra
# Copyright 2020 Gabriel Ferreira (@gabrielcarvfer)
# acousticbrainz-client is available under the terms of the GNU
# General Public License, version 3 or higher. See COPYING for more details.

import os
import shutil
import sys

host_address = "acousticbrainz.org"
#host_port = 4000
supported_extensions = ["mp3", "mp2",  "m2a", "ogg", "oga", "flac", "mp4", "m4a", "m4r",
                        "m4b", "m4p",  "aac", "wma", "asf",  "mpc",  "wv", "spx", "tta",
                        "3g2", "aif", "aiff", "ape",
                        ]

essentia_path = "streaming_extractor_music" + ("" if sys.platform != "win32" else ".exe")

def create_folder(path):
    if not os.path.exists(path):
        os.mkdir(path)

def main(paths, offline):
    from abz.acousticbrainz import scan_files_to_process, process_file
    import multiprocessing as mp
    import multiprocessing.dummy as dummy
    import hashlib
    from threading import Lock

    # Precompute extractor sha1
    h = hashlib.sha1()
    h.update(open(essentia_path, "rb").read())
    essentia_build_sha = h.hexdigest()
    del h

    # Get list of files to process
    files_to_process = scan_files_to_process(paths, supported_extensions)

    # Create shared dictionary to keep track of processed files
    shared_dict = {}
    shared_dict["essentia_path"] = essentia_path
    shared_dict["essentia_build_sha"] = essentia_build_sha
    shared_dict["offline"] = offline
    shared_dict["host"] = host_address
    shared_dict["lock"] = Lock()
    del essentia_build_sha

    # Create folder structure for failed/pending/successful submissions
    create_folder("features")
    create_folder("features/failed/")
    create_folder("features/failed/nombid")
    create_folder("features/failed/badmbid")
    create_folder("features/failed/extraction")
    create_folder("features/failed/unknownerror")
    create_folder("features/failed/submission")
    create_folder("features/failed/jsonerror")
    create_folder("features/pending/")
    create_folder("features/success/")

    # Look for previously processed files
    shared_dict["processed_files"] = {}
    feature_files = scan_files_to_process(["./features"], ["json"])
    for path in feature_files:
        state, error, filename = path.split(os.sep)[-3:]
        if state == "features":
            state = error
            error = None
        shared_dict["processed_files"][filename] = (state, error)
    del path, feature_files, state, error, filename

    # Retry sending previously saved features by moving them to the pending folder
    resubmit = []
    for (filename, (state, error)) in shared_dict["processed_files"].items():
        if state == "failed" and error == "submission":
            shutil.move("features/failed/submission/"+filename, "features/pending")
            resubmit.append(filename)
    del state, error
    for filename in resubmit:
        shared_dict["processed_files"][filename] = ("pending", None)
    del filename

    # Todo: add option to force new extraction (a.k.a. delete previously processed features file)

    try:
        # Pass shared dictionary and files to process to worker threads
        with dummy.Pool(processes=mp.cpu_count()-1) as pool:
            pool.starmap(process_file, zip([shared_dict]*len(files_to_process), files_to_process))
    except KeyboardInterrupt:
        # Prematurely interrupt workers
        pass

    print()


if __name__ == "__main__":
    from multiprocessing import freeze_support
    freeze_support()

    import argparse
    parser = argparse.ArgumentParser(description='Extract acoustic features from songs.')
    parser.add_argument('-o', '--offline', type=bool, default=False,
                        help='Extract features but skip submission (default: False)')
    parser.add_argument('-p', '--path-list', nargs="*")

    if len(sys.argv) < 2:
        parser.print_help()
        sys.exit(1)

    args = parser.parse_args()

    main(args.path_list, args.offline)
