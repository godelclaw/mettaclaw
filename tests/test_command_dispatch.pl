:- use_module(library(plunit)).
:- dynamic probe_count/1.

:- consult('../src/skills.pl').

eval([probe], Count) :-
    retract(probe_count(Previous)),
    Count is Previous + 1,
    assertz(probe_count(Count)).

'py-call'(['helper.normalize_string', Value], Value).

reset_probe :-
    retractall(probe_count(_)),
    assertz(probe_count(0)),
    catch(nb_delete(mettaclaw_command_batch_cache), _, true).

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

:- end_tests(command_dispatch).
