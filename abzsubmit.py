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

def file_state_thread(shared_dict):
    sys.stdout.reconfigure(encoding='utf-8')  # make sure to use utf-8 encoding on windows
    RESET_CHARACTER = "\x1b[0m"
    RED_CHARACTER = "\x1b[31m"
    GREEN_CHARACTER = "\x1b[32m"
    MAGENTA_CHARACTER = "\x1b[35m"
    CYAN_CHARACTER = "\x1b[36m"

    processing_sheet = {}
    processing_times = {"extraction": [],
                        "submission": []
                        }
    extracted = 0
    submitted = 0
    failed = 0
    remaining_jobs = 0
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

    while not shared_dict["end"] and not shared_dict["file_to_process_queue"].empty():
        filename, state, error, time_to_process = shared_dict["file_state_queue"].get()
        if filename == "END":
            break
        shared_dict["file_state_queue"].task_done()

        remaining_jobs = max(shared_dict["file_to_process_queue"].qsize(), remaining_jobs)

        # Filename has _.json appended (feature output)
        filename = filename[:-6]
        processing_sheet[filename] = (state, error)

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
            msg += ("was extracted. ")
            color = MAGENTA_CHARACTER
        elif state == "failed":
            failed += 1
            msg += ("failed with error %s. " % error)
            color = RED_CHARACTER
        else:
            msg += ("features are being extracted. ")
            color = CYAN_CHARACTER
        msg += ("Job %d/%d - Estimated remaining time is %s" % (extracted, extracted+remaining_jobs, estimated_remaining_time))
        print("%s%s%s" % (color, msg, RESET_CHARACTER))

        # Skip time to finish estimate
        if extracted == 0:
            continue

        # Re-estimate time to finish
        seconds = (total_extraction_time / extracted) * remaining_jobs
        days = int(seconds/86400)
        seconds = seconds - days*86400
        hours = int(seconds/3600)
        seconds = seconds - hours*3600
        minutes = int(seconds/60)
        estimated_remaining_time = ("%.dd:%dh:%dm" % (days, hours, minutes))
        del seconds, minutes, hours, days


def file_processor_thread(shared_dict):
    from abz.acousticbrainz import process_file

    # Check for files to process inside the queue
    while not shared_dict["end"]:
        file_to_process = shared_dict["file_to_process_queue"].get()
        if file_to_process == "END":
            break
        process_file(shared_dict, file_to_process, shared_dict["file_state_queue"])
        shared_dict["file_to_process_queue"].task_done()


def main(paths, offline, reprocess_failed, num_threads):
    from abz.acousticbrainz import scan_files_to_process
    import hashlib
    from queue import Queue
    from threading import Thread

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
    shared_dict["file_to_process_queue"] = Queue()
    shared_dict["file_state_queue"] = Queue()
    shared_dict["end"] = False
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
    if len(feature_files) > 0:
        del path, feature_files, state, error, filename

    # Retry sending previously saved features by moving them to the pending folder
    resubmit = []
    for (filename, (state, error)) in shared_dict["processed_files"].items():
        if state == "failed" and error == "submission":
            shutil.move("features/failed/submission/"+filename, "features/pending")
            resubmit.append(filename)
    if len(shared_dict["processed_files"]) > 0:
        del state, error
    for filename in resubmit:
        shared_dict["processed_files"][filename] = ("pending", None)
    if len(resubmit) > 0:
        del filename, resubmit

    # Reprocess previously saved features that failed
    if reprocess_failed:
        resubmit = []
        for (filename, (state, error)) in shared_dict["processed_files"].items():
            if state == "failed":
                shutil.move("features/failed/"+error+"/"+filename, "features/pending")
                resubmit.append(filename)
        if len(shared_dict["processed_files"]) > 0:
            del state, error
        for filename in resubmit:
            del shared_dict["processed_files"][filename]
        if len(resubmit) > 0:
            del filename, resubmit

    # Add files to process to the file_to_process_queue
    for filename in files_to_process:
        shared_dict["file_to_process_queue"].put((filename))

    threads = []
    # Create file_state_thread to keep up with CLI and GUI updates
    threads.append(Thread(target=file_state_thread, args=(shared_dict,)))

    # Create file_processor_thread to keep up with feature extraction
    for _ in range(num_threads):
        threads.append(Thread(target=file_processor_thread, args=(shared_dict,)))
        shared_dict["file_to_process_queue"].put(("END"))  # marker for threads to die at the end of queue

    # Release the kraken
    for thread in threads:
        thread.start()

    for thread in threads[1:]:
        try:
            thread.join()
        except Exception:
            pass

    # Wake up file state thread and let it know the program is ending
    shared_dict["end"] = True
    shared_dict["file_state_queue"].put(["END"]*4)  # marker to kill state thread after finished processing features

    # Wait for state thread to join
    thread[0].join()

    print("We are done here. Have a good day.")


if __name__ == "__main__":
    from multiprocessing import freeze_support, cpu_count
    freeze_support()

    import argparse
    parser = argparse.ArgumentParser(description='Extract acoustic features from songs.')
    parser.add_argument('-j', '--jobs', type=int, default=(cpu_count()-1),
                        help='Number of parallel jobs to execute')
    parser.add_argument('-o', '--offline', type=bool, default=False,
                        help='Extract features but skip submission (default: False)')
    parser.add_argument('-rf', '--reprocess-failed', type=bool, default=False,
                        help='Reprocess features that previously failed (default: False)')
    parser.add_argument('-p', '--path-list', nargs="*")

    if len(sys.argv) < 2:
        parser.print_help()
        sys.exit(1)

    args = parser.parse_args()

    main(args.path_list, args.offline, args.reprocess_failed, args.jobs)
