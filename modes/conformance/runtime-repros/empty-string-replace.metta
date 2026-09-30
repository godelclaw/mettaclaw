; PeTTa v1.0.4 returns an empty string; native CeTTa reports host-failure.
!(import_prolog_function atomic_list_concat)
!(import_prolog_function split_string)
!(atomic_list_concat (split_string "" "x" "") "_replacement_")
