;; lib_cettaclaw.metta — the CeTTaClaw agent library manifest.
;;
;; Pure CeTTa: no Python, no Prolog, no PeTTa libraries. The interpreter and its
;; native interfaces (http, json, str, fs, time, process, system, web) live in
;; CeTTa proper (CETTA_ROOT), not here. This manifest loads:
;;   * src/ — the thin agent core and its focused adapters
;;
;; Imports are transitive and de-duplicated. The real chat provider is src/llm;
;; offline tests import their own fixture
;; with the identical (claw:llm-chat ...) seam.

;; ---- agent core ------------------------------------------------------------
!(import! &self ./src/config.metta)
!(import! &self ./src/value.metta)
!(import! &self ./src/text.metta)
!(import! &self ./src/wire.metta)
!(import! &self ./src/telegram.metta)
!(import! &self ./src/llm.metta)
!(import! &self ./src/utils.metta)
!(import! &self ./src/memory.metta)
!(import! &self ./src/channels.metta)
!(import! &self ./src/search.metta)
!(import! &self ./src/mcp.metta)
!(import! &self ./src/skills.metta)
!(import! &self ./src/context.metta)
!(import! &self ./src/loop.metta)
