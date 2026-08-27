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
eval([observe], observed).
eval(['delete-my-recent'], "no recorded own-sends — nothing to delete").
eval([announce_done], sent).
eval([send, fail], "send failed: provider rejected request").
eval([send, ok], "sent message 9 to chat private").

'py-call'(['helper.normalize_string', Value], Value).
'py-call'(['effect_receipts.record_command', Turn, Disposition,
           Command, Result], 1) :-
    assertz(effect_receipt(Turn, Disposition, Command, Result)).
'py-call'(['effect_receipts.record_suffix', Turn, Disposition,
           Commands, Reason], 1) :-
    assertz(effect_receipt(Turn, Disposition, Commands, Reason)).
'py-call'(['telegram.effect_turn_stimulus_free', _], Value) :-
    stimulus_free(Value).
'py-call'(['action_graph.partition_after_stimulus', Commands],
          [Independent, Dependent]) :-
    partition_test_commands(Commands, Independent, Dependent).
'py-call'(['action_graph.result_permits_dependent_suffix',
           ['delete-my-recent'], _], 0) :- !.
'py-call'(['action_graph.result_permits_dependent_suffix', _, _], 1).

partition_test_commands([], [], []).
partition_test_commands([[observe]|Rest], [[observe]|Independent], Dependent) :-
    !, partition_test_commands(Rest, Independent, Dependent).
partition_test_commands([Command|Rest], Independent, [Command|Dependent]) :-
    partition_test_commands(Rest, Independent, Dependent).

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

test(new_stimulus_allows_only_certified_observation_suffix) :-
    reset_probe,
    'run-command-batch-once'(12, 5,
                             [[stimulate], [probe], [observe]], Records),
    probe_count(0),
    assertion(Records == [
        ['COMMAND_RETURN:', [[stimulate], ok]],
        ['COMMAND_BATCH_INTERRUPTED:',
         [reason, new_stimulus, commands, [[probe]]]],
        ['COMMAND_RETURN:', [[observe], observed]]
    ]),
    assertion(effect_receipt(12, withheld, [[probe]], new_stimulus)),
    assertion(effect_receipt(12, returned, [observe], observed)).

test(coding_limit_retains_five_commands) :-
    reset_probe,
    'run-command-batch-once'(10, 5,
                             [[probe], [probe], [probe], [probe], [probe]],
                             Records),
    probe_count(5),
    length(Records, 5).

test(failed_delete_withholds_done_but_keeps_observation) :-
    reset_probe,
    'run-command-batch-once'(13, 5,
                             [['delete-my-recent'], [announce_done],
                              [observe]], Records),
    assertion(Records == [
        ['COMMAND_RETURN:',
         [['delete-my-recent'],
          "no recorded own-sends — nothing to delete"]],
        ['COMMAND_BATCH_INTERRUPTED:',
         [reason, failed_effect, after, ['delete-my-recent'],
          commands, [[announce_done]]]],
        ['COMMAND_RETURN:', [[observe], observed]]
    ]),
    assertion(effect_receipt(
        13, withheld, [[announce_done]], failed_effect)).

test(failed_send_withholds_claim) :-
    reset_probe,
    'run-command-batch-once'(14, 5,
                             [[send, fail], [announce_done]], Records),
    assertion(Records == [
        ['COMMAND_RETURN:',
         [[send, fail], "send failed: provider rejected request"]],
        ['COMMAND_BATCH_INTERRUPTED:',
         [reason, failed_effect, after, [send, fail],
          commands, [[announce_done]]]]
    ]).

test(successful_send_keeps_permissive_suffix) :-
    reset_probe,
    'run-command-batch-once'(15, 5,
                             [[send, ok], [announce_done]], Records),
    assertion(Records == [
        ['COMMAND_RETURN:', [[send, ok],
                             "sent message 9 to chat private"]],
        ['COMMAND_RETURN:', [[announce_done], sent]]
    ]).

:- end_tests(command_dispatch).
