;; Text codecs and bounded views shared by the focused agent adapters.

!(import! &self str)
!(import! &self ./value.metta)

;; The action S-expression channel cannot carry raw newlines, quotes, or
;; apostrophes, so preserve Pettaclaw's byte-compatible sentinel codec.
(= (claw:str-replace-all $text $from $to)
   (str:join $to (str:split $from $text)))

(= (claw:encode-safe $text)
   (claw:str-replace-all
     (claw:str-replace-all
       (claw:str-replace-all $text "\n" "_newline_")
       "\"" "_quote_")
     "'" "_apostrophe_"))

(= (claw:decode-safe $text)
   (claw:str-replace-all
     (claw:str-replace-all
       (claw:str-replace-all $text "_newline_" "\n")
       "_quote_" "\"")
     "_apostrophe_" "'"))

;; Normalize repr-style escaped quote delimiters before displaying history or
;; decoding a fresh command batch.
(= (claw:decode-repr-quotes $text)
   (claw:str-replace-all $text "\\\"" "\""))

(= (claw:last-chars $text $n)
   (let $len (str:length $text)
        (str:slice $text (claw:max 0 (- $len $n)) $len)))
