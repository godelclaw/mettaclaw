:- use_module(library(plunit)).
:- dynamic probe_count/1.
:- dynamic stimulus_free/1.
:- dynamic effect_receipt/4.

:- consult('../src/skills.pl').

eval([probe], Count) :-
    retract(probe_count(Previous)),
    Count is Previous + 1,
    assertz(probe_count(Count)).
eval([stimulate], ok) :-
    retractall(stimulus_free(_)),
    assertz(stimulus_free(0)).

'py-call'(['helper.normalize_string', Value], Value).
'py-call'(['effect_receipts.record_command', Turn, Disposition,
           Command, Result], 1) :-
    assertz(effect_receipt(Turn, Disposition, Command, Result)).
'py-call'(['effect_receipts.record_suffix', Turn, Disposition,
           Commands, Reason], 1) :-
    assertz(effect_receipt(Turn, Disposition, Commands, Reason)).
'py-call'(['telegram.effect_turn_stimulus_free', _], Value) :-
    stimulus_free(Value).

reset_probe :-
    retractall(probe_count(_)),
    assertz(probe_count(0)),
    retractall(stimulus_free(_)),
    assertz(stimulus_free(1)),
    retractall(effect_receipt(_, _, _, _)),
    catch(nb_delete(mettaclaw_command_batch_cache), _, true).

:- begin_tests(command_dispatch).

test(reentry_reuses_cache_and_new_turn_executes) :-
    reset_probe,
    'run-command-batch-once'(7, 5, [[probe]], First),
    'run-command-batch-once'(7, 5, [[probe]], Replay),
    probe_count(1),
    assertion(First == Replay),
    assertion(First == [['COMMAND_RETURN:', [[probe], 1]]]),
    aggregate_all(count, effect_receipt(7, returned, [probe], 1), 1),
    'run-command-batch-once'(8, 5, [[probe]], SecondTurn),
    probe_count(2),
    assertion(SecondTurn == [['COMMAND_RETURN:', [[probe], 2]]]).

test(explicit_limit_defers_the_unadmitted_suffix) :-
    reset_probe,
    'run-command-batch-once'(9, 1,
                             [[probe], [probe], [probe]], Records),
    probe_count(1),
    assertion(Records == [
        ['COMMAND_RETURN:', [[probe], 1]],
        ['COMMAND_BATCH_DEFERRED:',
         [limit, 1, commands, [[probe], [probe]]]]
    ]),
    assertion(effect_receipt(9, deferred, [[probe], [probe]], batch_limit)).

test(new_stimulus_interrupts_only_the_unexecuted_suffix) :-
    reset_probe,
    'run-command-batch-once'(11, 5, [[stimulate], [probe]], Records),
    probe_count(0),
    assertion(Records == [
        ['COMMAND_RETURN:', [[stimulate], ok]],
        ['COMMAND_BATCH_INTERRUPTED:',
         [reason, new_stimulus, commands, [[probe]]]]
    ]),
    assertion(effect_receipt(11, returned, [stimulate], ok)),
    assertion(effect_receipt(11, withheld, [[probe]], new_stimulus)).

test(coding_limit_retains_five_commands) :-
    reset_probe,
    'run-command-batch-once'(10, 5,
                             [[probe], [probe], [probe], [probe], [probe]],
                             Records),
    probe_count(5),
    length(Records, 5).

:- end_tests(command_dispatch).
