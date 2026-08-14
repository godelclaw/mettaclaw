:- use_module(library(plunit)).
:- dynamic probe_count/1.
:- dynamic frontier_current/1.

:- consult('../src/skills.pl').

eval([probe], Count) :-
    retract(probe_count(Previous)),
    Count is Previous + 1,
    assertz(probe_count(Count)).
eval([advance], advanced) :-
    retractall(frontier_current(_)),
    assertz(frontier_current(0)).

'py-call'(['helper.normalize_string', Value], Value).
'py-call'(['helper.receipt_current', _Receipt], Current) :-
    frontier_current(Current).

reset_probe :-
    retractall(probe_count(_)),
    assertz(probe_count(0)),
    retractall(frontier_current(_)),
    assertz(frontier_current(1)),
    catch(nb_delete(mettaclaw_command_batch_cache), _, true).

set_frontier(Current) :-
    retractall(frontier_current(_)),
    assertz(frontier_current(Current)).

:- begin_tests(command_dispatch).

test(reentry_reuses_cache_and_new_turn_executes) :-
    reset_probe,
    'run-command-batch-once'(7, [[probe]], First),
    'run-command-batch-once'(7, [[probe]], Replay),
    probe_count(1),
    assertion(First == Replay),
    assertion(First == [['COMMAND_RETURN:', [[probe], 1]]]),
    'run-command-batch-once'(8, [[probe]], SecondTurn),
    probe_count(2),
    assertion(SecondTurn == [['COMMAND_RETURN:', [[probe], 2]]]).

test(stale_batch_runs_nothing) :-
    reset_probe,
    set_frontier(0),
    'run-command-batch-at-frontier'(receipt, revision, 9,
                                    [[probe]], Records),
    probe_count(0),
    assertion(Records = [['COMMAND_BATCH_DEFERRED:', _]]).

test(new_input_stops_remaining_commands) :-
    reset_probe,
    'run-command-batch-at-frontier'(receipt, revision, 10,
                                    [[advance], [probe]], Records),
    probe_count(0),
    assertion(Records == [
        ['COMMAND_RETURN:', [[advance], advanced]],
        ['COMMAND_DEFERRED_STALE_FRONTIER:', [probe]]
    ]).

:- end_tests(command_dispatch).
