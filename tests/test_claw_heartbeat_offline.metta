;; Quiet-time wake policy is deterministic at its boundary and disabled when
;; its profile value is zero. This exercises only loop state: no clock, channel,
;; network, provider, or sleep call escapes the fixture.

!(import! &self ../src/loop.metta)

!(claw:init 7 ())

!(let $a (change-state! &loops 0)
 (let $b (change-state! &sleep-ms 9000)
 (let $c (change-state! &heartbeat-interval-ms 1000)
 (let $d (change-state! &last-heartbeat-ms 10000)
      HeartbeatTestReady))))

;; Not early, and exactly at the configured threshold.
!(assertEqual (claw:maybe-heartbeat-at 10999) ClawNoop)
!(assertEqual (get-state &loops) 0)
!(assertEqual (get-state &sleep-ms) 9000)
!(assertEqual (get-state &last-heartbeat-ms) 10000)

!(assertEqual (claw:maybe-heartbeat-at 11000) ClawHeartbeatArmed)
!(assertEqual (get-state &loops) 7)
!(assertEqual (get-state &sleep-ms) 1000)
!(assertEqual (get-state &last-heartbeat-ms) 11000)

;; Repeated heartbeats saturate at max-loops; they never add another grant.
!(let $a (change-state! &loops 2)
 (claw:maybe-heartbeat-at 12000))
!(assertEqual (get-state &loops) 7)

;; Zero is an explicit opt-out regardless of elapsed wall time.
!(let $a (change-state! &heartbeat-interval-ms 0)
 (let $b (change-state! &loops 0)
      HeartbeatDisabled))
!(assertEqual (claw:maybe-heartbeat-at 99999) ClawNoop)
!(assertEqual (get-state &loops) 0)
