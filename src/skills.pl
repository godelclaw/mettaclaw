%Gets shell command return, plus the process if time limit is not met, returning timeout_error:
shell(Cmd, Out) :-
    tmp_file_stream(text, TmpFile, TmpInit),
    close(TmpInit),
    open(TmpFile, write, TmpOut, [type(text)]),
    catch(
        setup_call_cleanup(
            process_create(
                path(timeout),
                ['-k', '1s', '5s', 'sh', '-c', Cmd],
                [ stdout(stream(TmpOut)),
                  stderr(stream(TmpOut)),
                  process(P)
                ]
            ),
            (
                process_wait(P, Status),
                close(TmpOut),
                read_file_to_string(TmpFile, Text, [])
            ),
            (
                catch(close(TmpOut), _, true),
                catch(delete_file(TmpFile), _, true)
            )
        ),
        E,
        (
            catch(close(TmpOut), _, true),
            catch(delete_file(TmpFile), _, true),
            throw(E)
        )
    ),
    ( Status = exit(124) -> Out = timeout_error
    ; Status = exit(137) -> Out = timeout_error
    ; Status = killed(_) -> Out = timeout_error
    ; Text == "" ->
        %% Empty output was indistinguishable from a failed command, so a
        %% mistyped shell string looked exactly like "no matches found".
        %% Say which one happened.
        ( Status = exit(0)
          -> Out = "SHELL_OK_NO_OUTPUT (command succeeded, printed nothing)"
        ; Status = exit(Code)
          -> format(string(Out),
                    "SHELL_ERROR exit ~w (command failed, printed nothing)",
                    [Code])
        ; Out = "SHELL_ERROR (command did not exit normally)"
        )
    ; Out = Text
    ).


first_char(Str, C) :- sub_string(Str, 0, 1, _, C).

%% Commands cross the MeTTa -> Prolog boundary under an explicit quote.  The
%% quote keeps them inert until this deterministic dispatcher evaluates each
%% item once.  The turn cache also makes reduction retries observationally
%% silent.
'run-command-batch-once'(Turn, RequestedLimit, Commands, Records) :-
    command_batch_limit(RequestedLimit, Limit),
    ( nb_current(mettaclaw_command_batch_cache,
                 command_batch(CachedTurn, CachedLimit, CachedCommands,
                               CachedRecords, _CachedErrors)),
      CachedTurn == Turn
    -> ( CachedLimit == Limit,
         CachedCommands =@= Commands
       -> copy_term(CachedRecords, Records)
       ;  Records = [['COMMAND_BATCH_REJECTED:',
                      "different limit or commands proposed after turn commitment"]]
       )
    ; admit_command_prefix(Limit, Commands, Admitted, Deferred),
      run_command_list_unless_stimulus(Turn, Admitted,
                                       ExecutedRecords, Errors),
      deferred_command_record(Limit, Deferred, DeferredRecords),
      append(ExecutedRecords, DeferredRecords, Records),
      nb_setval(mettaclaw_command_batch_cache,
                command_batch(Turn, Limit, Commands, Records, Errors))
    ), !.

'command-batch-errors'(Turn, Errors) :-
    ( nb_current(mettaclaw_command_batch_cache,
                 command_batch(CachedTurn, _Limit, _Commands, _Records,
                               CachedErrors)),
      CachedTurn == Turn
    -> copy_term(CachedErrors, Errors)
    ; Errors = []
    ), !.

command_batch_limit(Requested, Requested) :-
    integer(Requested),
    Requested > 0, !.
command_batch_limit(_, 1).

admit_command_prefix(0, Commands, [], Commands) :- !.
admit_command_prefix(_, [], [], []) :- !.
admit_command_prefix(Limit, [Command|Rest], [Command|Admitted], Deferred) :-
    Next is Limit - 1,
    admit_command_prefix(Next, Rest, Admitted, Deferred).

deferred_command_record(_, [], []) :- !.
deferred_command_record(Limit, Deferred,
                        [['COMMAND_BATCH_DEFERRED:',
                          [limit, Limit, commands, Deferred]]]).

run_command_list_unless_stimulus(_, [], [], []).
run_command_list_unless_stimulus(Turn, Commands, Records, Errors) :-
    ( effect_turn_stimulus_free(Turn)
    -> Commands = [Command|Rest],
       run_command_once(Command, Record, CommandErrors),
       run_command_list_unless_stimulus(Turn, Rest, RestRecords, RestErrors),
       Records = [Record|RestRecords],
       append(CommandErrors, RestErrors, Errors)
    ; Records = [['COMMAND_BATCH_INTERRUPTED:',
                  [reason, new_stimulus, commands, Commands]]],
      Errors = []
    ).

effect_turn_stimulus_free(Turn) :-
    ( getenv('METTACLAW_EFFECT_BACKEND', 'tmux-shadow')
    -> catch('py-call'(['effect_backend.turn_stimulus_free', Turn], Value),
             _, fail)
    ;  catch('py-call'(['telegram.effect_turn_stimulus_free', Turn], Value),
             _, fail)
    ),
    ( Value == 1 ; Value == true ; Value == 'True' ), !.

run_command_once(Command, ['COMMAND_RETURN:', [Command, Normalized]], Errors) :-
    catch(( once(command_effect(Command, Raw)) -> Status = ok(Raw)
                                              ; Status = failed ),
          Exception,
          Status = exception(Exception)),
    command_status(Status, Command, Value, Errors),
    normalize_command_value(Value, Normalized).

%% Qualification replaces only the effect provider beneath the real parser
%% and batch dispatcher. Shadow mode is fail-closed: its Python provider has
%% no passthrough result, so an unsupported command cannot reach eval/2.
command_effect(Command, Value) :-
    getenv('METTACLAW_EFFECT_BACKEND', 'tmux-shadow'), !,
    'py-call'(['effect_backend.dispatch', Command], Outcome),
    shadow_effect_outcome(Outcome, Value).
command_effect(Command, _Value) :-
    ( ( getenv('METTACLAW_EFFECT_BACKEND_STATE', State), State \== '' )
    ; ( getenv('METTACLAW_EFFECT_BACKEND', Backend), Backend \== '',
        Backend \== 'tmux-shadow' )
    ), !,
    throw(error(permission_error(execute, effect_backend, Command),
                context(command_effect/2,
                        'inconsistent shadow effect configuration'))).
command_effect(Command, Value) :-
    eval(Command, Value).

shadow_effect_outcome([handled, Value], Value) :- !.
shadow_effect_outcome(["handled", Value], Value) :- !.
shadow_effect_outcome(Outcome,
                      ['Error', invalid_shadow_effect_outcome, Outcome]).

command_status(ok(Value), _Command, Value, []).
command_status(failed, Command, ['Error', command_failed],
               [['command_format_error_nothing_ran', Command,
                 "command returned no result"]]).
command_status(exception(Exception), Command, ['Error', Message],
               [['command_format_error_nothing_ran', Command, Message]]) :-
    message_to_string(Exception, Message).

normalize_command_value(Value, Normalized) :-
    ( catch('py-call'(['helper.normalize_string', Value], Normalized), _, fail)
    -> true
    ; with_output_to(string(Normalized),
                     write_term(Value, [quoted(true)]))
    ).

gc(true) :-
    garbage_collect,
    garbage_collect_atoms,
    trim_stacks.
