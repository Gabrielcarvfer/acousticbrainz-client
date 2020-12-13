#!/usr/bin/env python

# Client for submitting feature files to the AcousticBrainz project

# Copyright 2014 Music Technology Group - Universitat Pompeu Fabra
# Copyright 2020 Gabriel Ferreira (@gabrielcarvfer)
# acousticbrainz-client is available under the terms of the GNU
# General Public License, version 3 or higher. See COPYING for more details.

import os
import shutil
import sys


def main(paths, offline, reprocess_failed, num_threads, host_address, essentia_path):
    from threading import Thread
    from abz.abzsubmit_common import (supported_extensions,
                                      create_folder_structure,
                                      create_shared_dictionary,
                                      scan_files_to_process,
                                      scan_previously_processed_features,
                                      retry_submitting_features,
                                      reprocess_failed_features,
                                      file_state_thread,
                                      file_processor_thread,
                                      )
    # Create folder structure for failed/pending/successful submissions
    create_folder_structure()

    # Create shared dictionary to keep track of processed files
    shared_dict = create_shared_dictionary(essentia_path, offline, host_address)

    # Get list of files to process
    files_to_process = scan_files_to_process(paths, supported_extensions)

    # Process previously extracted features
    shared_dict["processed_files"] = scan_previously_processed_features()
    shared_dict["processed_files"] = retry_submitting_features(shared_dict["processed_files"])
    if reprocess_failed:
        shared_dict["processed_files"] = reprocess_failed_features(shared_dict["processed_files"])

    # Add files to process to the file_to_process_queue
    for filename in files_to_process:
        shared_dict["file_to_process_queue"].put(filename)

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
    threads[0].join()

    print("We are done here. Have a good day.")


if __name__ == "__main__":
    from multiprocessing import freeze_support
    freeze_support()

    from abz.abzsubmit_common import parse_arguments
    args = parse_arguments()

    main(args.path_list, args.offline, args.reprocess_failed, args.jobs, args.host_address, args.essentia_path)
