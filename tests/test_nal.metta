!(import! &self (library lib_he))
!(import! &self ./lib_nal)
!(import! &self ./lib_nal7)

!(assertEqual (Truth_Negation (stv 0.75 0.8)) (stv 0.25 0.8))
!(assertEqual (Truth_Deduction (stv 1.0 0.9) (stv 0.8 0.7))
               (stv 0.8 0.504))
