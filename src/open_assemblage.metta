;; An open collection of named coordinates.  Policy names and state fields are
;; data: adding one does not add a case to process-step.
(= (coordinate-get $selected coordinates-empty)
   (missing-coordinate $selected))
(= (coordinate-get $selected (coordinate $name $value $rest))
   (if (== $selected $name)
       $value
       (coordinate-get $selected $rest)))

(= (coordinate-get-or $selected $default $coordinates)
   (let $found (coordinate-get $selected $coordinates)
        (case $found
          (((missing-coordinate $name) $default)
           ($value $value)))))

(= (coordinate-set $selected $value coordinates-empty)
   (coordinate $selected $value coordinates-empty))
(= (coordinate-set $selected $value (coordinate $name $old $rest))
   (if (== $selected $name)
       (coordinate $name $value $rest)
       (coordinate $name $old (coordinate-set $selected $value $rest))))

(= (coordinate-overlay coordinates-empty $base) $base)
(= (coordinate-overlay (coordinate $name $value $rest) $base)
   (coordinate-overlay $rest (coordinate-set $name $value $base)))

(= (process-root (rooted $root $periphery)) $root)
(= (process-periphery (rooted $root $periphery)) $periphery)
