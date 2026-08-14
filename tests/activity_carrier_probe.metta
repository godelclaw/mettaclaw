!(import! &self (library lib_he))
!(import! &self ./src/helper.py)

!(assertEqual (py-call (helper.text_nonempty "")) 0)
!(assertEqual (py-call (helper.text_nonempty "activity")) 1)
!(println! ACTIVITY_CARRIER_OK)
