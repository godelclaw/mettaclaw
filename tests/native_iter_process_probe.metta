!(import! &self (library lib_import))
!(import! &self ./src/metta_coding_policy)
!(import_prolog_functions_from_file ./src/native_iter.pl (iter-native-run))

!(let $result
     (iter-native-run
       tests/fixtures/native_iter_transformations
       (coding-view
         (coding-message-list
           (coding-message system hello) coding-messages-empty)
         advertised))
     (progn
       (println! $result)
       (println! NATIVE_ITER_PROCESS_OK)))
