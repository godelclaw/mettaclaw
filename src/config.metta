;; src/config.metta — CeTTaClaw's KEY=VALUE settings/secrets reader.
;; Values may contain '=', so split on the key prefix rather than every '='.
;; Lookups re-read the file and occur only at boot or explicit probes.

!(import! &self fs)
!(import! &self str)
!(import! &self system)

;; Normalise a line to its bare "KEY=VALUE" form: trim, then drop a leading
;; "export " so the byte-exact pettaclaw-generated .env (which uses
;; `export KEY='value'`) parses the same as a plain KEY=VALUE file.
(= (claw:norm-line $line)
   (let $t (str:trim $line)
        (if (str:starts-with $t "export ")
            (str:slice $t 7 (str:length $t))
            $t)))

;; Strip one matching pair of surrounding single or double quotes.
(= (claw:unquote $v)
   (if (and (>= (str:length $v) 2)
            (or (and (str:starts-with $v "'") (str:ends-with $v "'"))
                (and (str:starts-with $v "\"") (str:ends-with $v "\""))))
       (str:slice $v 1 (- (str:length $v) 1))
       $v))

;; Value of "KEY=..." in a normalised $line, unquoted.
(= (claw:kv-value $line $prefix)
   (claw:unquote (str:slice $line (str:length $prefix) (str:length $line))))

;; First line whose normalised form starts with "KEY="; NotFound otherwise.
;; filter-atom's predicate must be wrapped in (eval ...); str:split takes the
;; separator first.
(= (claw:env-lookup $text $key)
   (let $prefix (str:concat $key "=")
   (let $lines (str:split "\n" $text)
   (let $hits (filter-atom $lines $l
                (eval (str:starts-with (claw:norm-line $l) $prefix)))
        (if (== $hits ())
            NotFound
            (claw:kv-value (claw:norm-line (car-atom $hits)) $prefix))))))

(= (claw:config-get $path $key)
   (case (fs:read-text $path)
     (((FsError $msg) NotFound)
      ($text (claw:env-lookup $text $key)))))

;; Standard config locations. getenv-or-default returns its default
;; UNEVALUATED when the var is absent, so the computed fallback path must be
;; forced with let before it is passed in.
(= (claw:home)
   (system:getenv-or-default "HOME" "."))

(= (claw:secrets-path)
   (let $fallback (str:concat (claw:home) "/.config/cettaclaw/secrets.env")
        (system:getenv-or-default "CETTACLAW_SECRETS" $fallback)))

(= (claw:settings-path)
   (let $fallback (str:concat (claw:home) "/.config/cettaclaw/settings.env")
        (system:getenv-or-default "CETTACLAW_SETTINGS" $fallback)))

(= (claw:secret $key)
   (let $p (claw:secrets-path) (claw:config-get $p $key)))

(= (claw:setting $key)
   (let $p (claw:settings-path) (claw:config-get $p $key)))
