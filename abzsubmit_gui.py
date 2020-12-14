import PySimpleGUI as sg
from abz.abzsubmit_common import supported_extensions

extensions = [(ext, "."+ext) for ext in supported_extensions]


def update_entry_from_listbox(window, target_listbox_key, filename):
    for key in ["_PENDING_", "_FAILED_", "_EXTRACTED_", "_DUPLICATE_", "_SUBMITTED_"]:
        try:
            tmp = window[key].Values
            tmp = tmp.remove(filename)
            window[key].Update(tmp)
        except ValueError:
            pass
    window[target_listbox_key].Update([filename]+window[target_listbox_key].Values)


def main(paths, offline, reprocess_failed, num_threads, host_address, essentia_path):
    import os
    from queue import Queue
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

    # Get list of files to process and add files to process to the file_to_process_queue
    if paths:
        files_to_process = scan_files_to_process(paths, supported_extensions)
        for filename in files_to_process:
            shared_dict["file_to_process_queue"].put((filename))

    # Process previously extracted features
    shared_dict["processed_files"] = scan_previously_processed_features()
    shared_dict["processed_files"] = retry_submitting_features(shared_dict["processed_files"])
    if reprocess_failed:
        shared_dict["processed_files"] = reprocess_failed_features(shared_dict["processed_files"])

    # Setup UI
    menu_def = [['&Menu', ['&Add directory', '&Add file', '&Options', '&Quit']],
                ]

    # Define the window's contents
    #sg.VerticalSeparator(pad=None)
    layout = [[sg.Menu(menu_def, tearoff=False, pad=(200, 1))],
              [sg.Frame('Pending',    [[sg.LB(values=[], key="_PENDING_", size=(35, 20)), ], ]),
               sg.Frame('Extracted',  [[sg.LB(values=[], key="_EXTRACTED_", size=(35, 20)), ], ]),
               sg.Frame('Failed',     [[sg.LB(values=[], key="_FAILED_", size=(35, 20)), ], ]),
               sg.Frame('Duplicate',  [[sg.LB(values=[], key="_DUPLICATE_", size=(35, 20)), ], ]),
               sg.Frame('Submitted',  [[sg.LB(values=[], key="_SUBMITTED_", size=(35, 20)), ], ]),
               ],
              ]

    # Create the main window
    window = sg.Window('Window Title', layout)

    # Keep track of file states for GUI updates
    processing_sheet = {}
    gui_queue = Queue()

    threads = []
    # Create file_state_thread to keep up with CLI and GUI updates
    threads.append(Thread(target=file_state_thread, args=(shared_dict, gui_queue)))

    # Create file_processor_thread to keep up with feature extraction
    for _ in range(num_threads):
        threads.append(Thread(target=file_processor_thread, args=(shared_dict,)))

    # Release the kraken
    for thread in threads:
        thread.start()

    window.read(timeout=0.1)

    processed_groups = {}
    for (filename, result) in shared_dict["processed_files"].items():
        processing_sheet[filename] = result[0]
        if result[0] not in processed_groups:
            processed_groups[result[0]] = []
        processed_groups[result[0]].append(filename[:-6])
    for group in processed_groups.keys():
        if group == 'failed':
            window["_FAILED_"].Update(processed_groups[group])
        elif group == 'pending':
            window["_EXTRACTED_"].Update(processed_groups[group])
        elif group == 'duplicate':
            window["_DUPLICATE_"].Update(processed_groups[group])
        elif group == 'success':
            window["_SUBMITTED_"].Update(processed_groups[group])
        else:
            pass
    if len(processed_groups) > 0:
        del processed_groups

    # Display and interact with the Window using an Event Loop
    while True:
        event, values = window.read(timeout=10)

        # See if user wants to quit or window was closed
        if event == sg.WINDOW_CLOSED or event == 'Quit':
            break


        # ------ Process menu choices ------ #
        if event == 'Add directory':
            path = sg.popup_get_folder('folder to open', no_window=True)
            files_to_process = scan_files_to_process([path], supported_extensions)
            for filename in files_to_process:
                shared_dict["file_to_process_queue"].put(filename)
            #print("Adding directory: ", path)
        elif event == 'Add file':
            filename = sg.popup_get_file('file to open', no_window=True, file_types=extensions)
            shared_dict["file_to_process_queue"].put(filename)
            #print("Adding file: ", filename)
        else:
            if not gui_queue.empty():
                filename, state = gui_queue.get()
                gui_queue.task_done()

                if state == 'pending':
                    update_entry_from_listbox(window, "_PENDING_", filename)
                elif state == 'failed':
                    update_entry_from_listbox(window, "_FAILED_", filename)
                elif state == 'extracted':
                    update_entry_from_listbox(window, "_EXTRACTED_", filename)
                elif state == 'duplicate':
                    update_entry_from_listbox(window, "_DUPLICATE_", filename)
                else:
                    update_entry_from_listbox(window, "_SUBMITTED_", filename)
                processing_sheet[filename] = state
            pass

    # Finish up by removing from the screen
    window.close()


if __name__ == "__main__":
    from multiprocessing import freeze_support
    freeze_support()

    from abz.abzsubmit_common import parse_arguments
    args = parse_arguments(cli=False)

    main(args.path_list, args.offline, args.reprocess_failed, args.jobs, args.host_address, args.essentia_path)