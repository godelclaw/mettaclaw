!(import! &self (library lib_import))
!(import_prolog_functions_from_file "tests/fixtures/gateway_native_fault.pl" (gateway-native-identity gateway-native-invalid))
!(gateway-native-invalid)
!(println! SHOULD_NOT_RUN)
