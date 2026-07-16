;; Legacy command-wire normalization. The affect trace is a second output
;; channel and is removed only when it is one complete final line.

!(import! &self str)
!(import! &self ./text.metta)

(= (claw:strip-leading $text $ch)
   (if (str:starts-with $text $ch)
       (claw:strip-leading (str:slice $text 1 (str:length $text)) $ch)
       $text))

(= (claw:strip-trailing $text $ch)
   (if (str:ends-with $text $ch)
       (claw:strip-trailing (str:slice $text 0 (- (str:length $text) 1)) $ch)
       $text))

(= (claw:strip-trailing-affect $text)
   (let $trimmed (str:trim $text)
     (if (and (str:starts-with $trimmed "⋄⟨")
              (str:ends-with $trimmed "⟩"))
         (case (str:find $trimmed "\n")
           ((Empty "")
            ($later $text)))
         (if (str:ends-with $trimmed "⟩")
             (case (str:find $trimmed "\n⋄⟨")
               ((Empty $text)
                ($i (let $trace (str:slice $trimmed (+ $i 1) (str:length $trimmed))
                      (case (str:find $trace "\n")
                        ((Empty (str:slice $trimmed 0 $i))
                         ($later $text)))))))
             $text))))

;; Migration normalizer: unwrap the legacy command batch, normalize repr-style
;; quotes, and return exactly one outer command-list expression.
(= (claw:balance-parens $text)
   (let $trimmed (str:trim (claw:strip-trailing-affect $text))
   (let $core (str:trim
                (claw:strip-trailing
                  (claw:strip-leading $trimmed "(")
                  ")"))
        (str:concat "((" (str:concat (claw:decode-repr-quotes $core) "))")))))
