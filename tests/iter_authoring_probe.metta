!(import! &self (library lib_import))
!(import! &self ./lib_mettaclaw)

!(iter-transform-write
    "10_probe.metta"
    "(= (iter-transform $visible) (success $visible))\n")
!(iter-process-prepare-request system activity advertised 1)
!(iter-transform-disable "10_probe.metta")
!(iter-process-prepare-request system activity advertised 1)
!(iter-transform-enable "10_probe.metta")
!(iter-transformations)
!(println! ITER_AUTHORING_OK)
