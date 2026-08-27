!(import! &self (library lib_import))
!(import! &self ./lib_mettaclaw)

!(iter-transform-write
    "10_probe.py"
    "def transform(messages, tools):\n    return messages + [2], tools\n")
!(iter-process-run-json
    (py-call (iter_process_adapter.configured_directory)) "[1]" "[]")
!(iter-transform-disable "10_probe.py")
!(iter-process-run-json
    (py-call (iter_process_adapter.configured_directory)) "[1]" "[]")
!(iter-transform-enable "10_probe.py")
!(iter-transformations)
!(println! ITER_AUTHORING_OK)
