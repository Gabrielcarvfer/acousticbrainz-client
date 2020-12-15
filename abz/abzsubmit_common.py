#!/usr/bin/env python

# Common components for AcousticBrainz CLI and GUI clients

# Copyright 2020 Gabriel Ferreira (@gabrielcarvfer)
# acousticbrainz-client is available under the terms of the GNU
# General Public License, version 3 or higher. See COPYING for more details.

import os
import sys


# host_port = 4000
supported_extensions = ["mp3", "mp2",  "m2a", "ogg", "oga", "flac", "mp4", "m4a", "m4r",
                        "m4b", "m4p",  "aac", "wma", "asf",  "mpc",  "wv", "spx", "tta",
                        "3g2", "aif", "aiff", "ape",
                        ]


def parse_arguments(cli=True):
    import argparse
    from multiprocessing import cpu_count

    parser = argparse.ArgumentParser(description='Extract acoustic features from songs.')
    parser.add_argument('-j', '--jobs', type=int, default=(cpu_count()-1),
                        help='Number of parallel jobs to execute')
    parser.add_argument('-o', '--offline', type=bool, default=False,
                        help='Extract features but skip submission (default: False)')
    parser.add_argument('-rf', '--reprocess-failed', type=bool, default=False,
                        help='Reprocess features that previously failed (default: False)')
    parser.add_argument('-ha', '--host-address', type=str, default="acousticbrainz.org",
                        help='AcousticBrainz server address')
    parser.add_argument('-ep', '--essentia-path', type=str,
                        default=("streaming_extractor_music" + ("" if sys.platform != "win32" else ".exe")),
                        help='Path to streaming_extractor_music')
    parser.add_argument('-p', '--path-list', nargs="*")

    if cli and len(sys.argv) < 2:
        parser.print_help()
        sys.exit(1)

    args = parser.parse_args()
    return args


def create_folder(path):
    if not os.path.exists(path):
        os.mkdir(path)


def precompute_extractor_sha(essentia_path):
    # Precompute extractor sha1
    import hashlib
    h = hashlib.sha1()
    h.update(open(essentia_path, "rb").read())
    return h.hexdigest()


def check_extractor_version(essentia_path):
    import subprocess
    """ returns something like this (at least on windows)
    'Error: wrong number of arguments\r\n
    Usage: streaming_extractor_music.exe input_audiofile output_textfile [profile]\r\n
    \r\n
    Music extractor version 'music 1.0'\r\n
    built with Essentia version v2.1_beta2-1-ge3940c0\r\n
    \r\n
    '
    """
    ret = subprocess.run([essentia_path], stdout=subprocess.PIPE)

    """ filters the useful line
    'built with Essentia version v2.1_beta2-1-ge3940c0\r'
    """
    out = ret.stdout.decode(sys.stdout.encoding).split('\n')[-2]

    """ removes carrier return (if it is there)
    'built with Essentia version v2.1_beta2-1-ge3940c0\r'
    """
    cr = out[-1] == '\r'
    out = out[:-cr]

    """ tokenize and pick last item (a.k.a) version number
    'built with Essentia version **v2.1_beta2-1-ge3940c0**'
    """
    out = out.split(' ')[-1]
    return out


def create_folder_structure():
    # Create folder structure for failed/pending/successful submissions
    create_folder("./features")
    create_folder("./features/failed")
    create_folder("./features/failed/nombid")
    create_folder("./features/failed/badmbid")
    create_folder("./features/failed/extraction")
    create_folder("./features/failed/unknownerror")
    create_folder("./features/failed/submission")
    create_folder("./features/failed/jsonerror")
    create_folder("./features/failed/notrackid")
    create_folder("./features/pending")
    create_folder("./features/duplicate")
    create_folder("./features/success")


def create_shared_dictionary(essentia_path, offline, host_address):
    from queue import Queue
    shared_dict = {}
    shared_dict["essentia_path"] = essentia_path
    shared_dict["essentia_version"] = check_extractor_version(essentia_path)
    shared_dict["essentia_build_sha"] = precompute_extractor_sha(essentia_path)
    shared_dict["offline"] = offline
    shared_dict["host"] = host_address
    shared_dict["file_to_process_queue"] = Queue()
    shared_dict["file_state_queue"] = Queue()
    shared_dict["number_of_jobs_queue"] = Queue()
    shared_dict["end"] = False
    return shared_dict


def scan_files_to_process(paths, supported_extensions):
    files_to_process = []
    for path in paths:
        print("Processing %s" % path)
        for dirpath, dirnames, filenames in os.walk(path):
            for f in filenames:
                if f.lower().split(".")[-1] in supported_extensions:
                    files_to_process.append(os.path.abspath(os.path.join(dirpath, f)))
    return files_to_process


def scan_previously_processed_features():
    # Look for previously processed files
    processed_files_dict = {}
    feature_files = scan_files_to_process(["./features"], ["json"])
    for path in feature_files:
        state, error, filename = path.split(os.sep)[-3:]
        if state == "features":
            state = error
            error = None
        processed_files_dict[filename] = (state, error)
    if len(feature_files) > 0:
        del path, feature_files, state, error, filename
    return processed_files_dict


def retry_submitting_features(processed_files_dict):
    # Retry sending previously saved features by moving them to the pending folder
    import shutil
    resubmit = []
    for (filename, (state, error)) in processed_files_dict.items():
        if state == "failed" and error == "submission":
            shutil.move("features/failed/submission/"+filename, "features/pending")
            resubmit.append(filename)
    if len(processed_files_dict) > 0:
        del state, error
    for filename in resubmit:
        processed_files_dict[filename] = ("pending", None)
    if len(resubmit) > 0:
        del filename, resubmit
    return processed_files_dict


def reprocess_failed_features(processed_files_dict):
    # Reprocess previously saved features that failed
    import shutil
    resubmit = []
    for (filename, (state, error)) in processed_files_dict.items():
        if state == "failed":
            shutil.move("features/failed/"+error+"/"+filename, "features/pending")
            resubmit.append(filename)
    if len(processed_files_dict) > 0:
        del state, error
    for filename in resubmit:
        del processed_files_dict[filename]
    if len(resubmit) > 0:
        del filename, resubmit
    return processed_files_dict


def file_state_thread(shared_dict, gui_queue=None):
    import time
    cli = True if gui_queue is None else False

    sys.stdout.reconfigure(encoding='utf-8')  # make sure to use utf-8 encoding on windows
    RESET_CHARACTER = "\x1b[0m"
    RED_CHARACTER = "\x1b[31m"
    GREEN_CHARACTER = "\x1b[32m"
    YELLOW_CHARACTER = "\x1b[33m"
    MAGENTA_CHARACTER = "\x1b[35m"
    CYAN_CHARACTER = "\x1b[36m"

    processing_sheet = {}
    processing_times = {"extraction": [],
                        "submission": []
                        }
    extracted = 0
    submitted = 0
    failed = 0
    total_jobs = 0
    estimated_remaining_time = ("%.0fd:%.0fh:%.0fm" % (0, 0, 0))
    total_extraction_time = 0.0

    print("Previously processed files include:")
    for (filename, result) in shared_dict["processed_files"].items():
        filename = filename[:-6]
        msg = ""
        if result[0] == "success":
            msg += ("\t%s was submitted" % (filename))
            color = GREEN_CHARACTER
        elif result[0] == "failed":
            msg += ("\t%s failed with error %s" % (filename, result[1]))
            color = RED_CHARACTER
        else:
            msg += ("\t%s submission is pending" % (filename))
            color = MAGENTA_CHARACTER
        print("%s%s%s" % (color, msg, RESET_CHARACTER))
    if len(shared_dict["processed_files"]) > 0:
        del filename, result, msg, color

    print()
    print("Currently processed files:")

    while not shared_dict["end"]:
        # Keep track of jobs
        if not shared_dict["number_of_jobs_queue"].empty():
            total_jobs += shared_dict["number_of_jobs_queue"].get()
            shared_dict["number_of_jobs_queue"].task_done()

        # Dequeue change in file state
        filename, state, error, time_to_process = shared_dict["file_state_queue"].get()
        shared_dict["file_state_queue"].task_done()

        if filename == "END":
            break

        # Filename has _.json appended (feature output)
        filename = filename[:-6]
        processing_sheet[filename] = (state, error)

        # If gui, update tables based on processing sheet
        if not cli:
            gui_queue.put((filename, state))

        # Unused, but allows to keep track of processing time
        if state == "success" or error == "submission":
            processing_times["submission"].append(time_to_process)
        else:
            processing_times["extraction"].append(time_to_process)
            total_extraction_time += time_to_process

        # Account for finished jobs
        msg = "\t%s " % filename
        color = RESET_CHARACTER
        if state == "success":
            submitted += 1
            msg += ("was %s. " % ("submitted" if error == "" else " a duplicate"))
            color = GREEN_CHARACTER
        elif state == "extracted":
            extracted += 1
            msg += "was extracted. "
            color = MAGENTA_CHARACTER
        elif state == "failed":
            failed += 1
            msg += ("failed with error %s. " % error)
            color = RED_CHARACTER
        elif state == "pending":
            msg += "features are being extracted. "
            color = CYAN_CHARACTER
        elif state == "duplicate":
            msg += "features are duplicates. "
            color = YELLOW_CHARACTER
        msg += ("Job %d/%d - Estimated remaining time is %s" % (extracted+failed+submitted,
                                                                total_jobs,
                                                                estimated_remaining_time)
                )
        print("%s%s%s" % (color, msg, RESET_CHARACTER))

        # Re-estimate time to finish
        if extracted > 1:
            seconds = (total_extraction_time / extracted) * (total_jobs-extracted)
            seconds = max(seconds, 0)
            days = int(seconds/86400)
            seconds = seconds - days*86400
            hours = int(seconds/3600)
            seconds = seconds - hours*3600
            minutes = int(seconds/60)
            estimated_remaining_time = ("%.dd:%dh:%dm" % (days, hours, minutes))
            del seconds, minutes, hours, days

    # Clean queue
    while not shared_dict["file_state_queue"].empty():
        shared_dict["file_state_queue"].get()
        shared_dict["file_state_queue"].task_done()
    return


def file_processor_thread(shared_dict):
    from abz.acousticbrainz import process_file

    # Check for files to process inside the queue
    while not shared_dict["end"]:
        file_to_process = shared_dict["file_to_process_queue"].get()
        if file_to_process == "END":
            break
        process_file(shared_dict, file_to_process, shared_dict["file_state_queue"])
        shared_dict["file_to_process_queue"].task_done()

    # Clean queue when ending
    while not shared_dict["file_to_process_queue"].empty():
        shared_dict["file_to_process_queue"].get()
        shared_dict["file_to_process_queue"].task_done()

    # Wake up file_state_thread
    shared_dict["file_state_queue"].put(["END"]*4)  # marker to kill state thread after finished processing features
    pass
