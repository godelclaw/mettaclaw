;; Offline golden for claw/config.metta's env-file parser. Uses inline text
;; (no file I/O, no secrets, CWD-independent).
!(import! &self ../src/config.metta)

;; Basic key.
!(assertEqual (claw:env-lookup "FOO=bar" "FOO") "bar")

;; Values may contain '=' (API keys / base64): only the key prefix is split.
!(assertEqual (claw:env-lookup "FOO=bar\nKEY=abc=def==" "KEY") "abc=def==")

;; Comments and blank lines are ignored; later key still found.
!(assertEqual (claw:env-lookup "# a comment\n\nFOO=bar\nBAZ=qux" "BAZ") "qux")

;; Leading/trailing whitespace around a line is trimmed before matching.
!(assertEqual (claw:env-lookup "  FOO=bar  " "FOO") "bar")

;; Missing key -> NotFound (not a crash, not empty string).
!(assertEqual (claw:env-lookup "FOO=bar" "MISSING") NotFound)

;; A key that is a prefix of another is not confused for it.
!(assertEqual (claw:env-lookup "FOOBAR=1\nFOO=2" "FOO") "2")

;; The byte-exact pettaclaw-generated .env form: `export KEY='value'`.
!(assertEqual (claw:env-lookup "export SYNTHETIC_MODEL='syn:large:text'" "SYNTHETIC_MODEL") "syn:large:text")

;; Double-quoted values are unquoted too.
!(assertEqual (claw:env-lookup "export OWNER=\"someone\"" "OWNER") "someone")

;; A quoted value that itself contains '=' survives intact.
!(assertEqual (claw:env-lookup "export IDS='1,-100,-200'" "IDS") "1,-100,-200")

;; Missing config files are absent settings, not live-loop-breaking errors.
!(assertEqual (claw:config-get "runtime/test_claw_missing_config.env" "FOO") NotFound)
