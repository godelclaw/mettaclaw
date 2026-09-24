;; The program without its start: run.metta minus !(mettaclaw).  The CeTTa
;; launch loads this and then cetta_run.metta; probes load it before their own file.
!(import! &self (library lib_import))
!(import! &self ./lib_mettaclaw)
