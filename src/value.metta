;; Numeric and argument-value compatibility helpers used by action adapters.

!(import! &self str)

(= (claw:max $a $b) (if (> $a $b) $a $b))
(= (claw:min $a $b) (if (< $a $b) $a $b))

(= (claw:strip-repr-quotes $text)
   (if (and (>= (str:length $text) 2)
            (and (str:starts-with $text "\"")
                 (str:ends-with $text "\"")))
       (str:slice $text 1 (- (str:length $text) 1))
       $text))

(= (claw:arg-text $value)
   (claw:strip-repr-quotes (repr $value)))

(= (claw:digit-value $digit)
   (case $digit
     (("0" 0) ("1" 1) ("2" 2) ("3" 3) ("4" 4)
      ("5" 5) ("6" 6) ("7" 7) ("8" 8) ("9" 9)
      ($other InvalidNumber))))

(= (claw:parse-nat-loop $text $i $acc)
   (if (>= $i (str:length $text))
       $acc
       (let $digit (str:slice $text $i (+ $i 1))
       (let $value (claw:digit-value $digit)
            (case $value
              ((InvalidNumber InvalidNumber)
               ($n (claw:parse-nat-loop $text (+ $i 1) (+ (* $acc 10) $n)))))))))

(= (claw:parse-nat-arg $value)
   (let $text (str:trim (claw:arg-text $value))
        (if (== $text "")
            InvalidNumber
            (claw:parse-nat-loop $text 0 0))))
