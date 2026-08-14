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

%% External commands live on the deterministic side of the MeTTa/Prolog
%% boundary.  The non-backtrackable turn cache is the commitment record: if
%% the surrounding MeTTa reduction revisits this call, return the first result
%% without performing any command again.
'run-command-batch-once'(Turn, Commands, Records) :-
    ( nb_current(mettaclaw_command_batch_cache,
                 command_batch(CachedTurn, CachedCommands,
                               CachedRecords, _CachedErrors)),
      CachedTurn == Turn
    -> ( CachedCommands =@= Commands
       -> copy_term(CachedRecords, Records)
       ;  Records = [['COMMAND_BATCH_REJECTED:',
                      "different commands proposed after turn commitment"]]
       )
    ; run_command_list_once(Commands, Records, Errors),
      nb_setval(mettaclaw_command_batch_cache,
                command_batch(Turn, Commands, Records, Errors))
    ), !.

%% The single-kernel path adds a causal-frontier certificate to the existing
%% non-backtrackable turn cache.  The whole batch is deferred if it is stale at
%% entry, and freshness is rechecked before each later command so new input can
%% stop the remainder of a long-running batch.
'run-command-batch-at-frontier'(Receipt, Revision, Turn, Commands, Records) :-
    ( nb_current(mettaclaw_command_batch_cache,
                 command_batch_frontier(CachedReceipt, CachedTurn,
                                        CachedCommands, CachedRecords,
                                        _CachedErrors)),
      CachedReceipt == Receipt,
      CachedTurn == Turn
    -> ( CachedCommands =@= Commands
       -> copy_term(CachedRecords, Records)
       ;  Records = [['COMMAND_BATCH_REJECTED:',
                      "different commands proposed after turn commitment"]]
       )
    ; receipt_current(Receipt, Revision)
    -> run_command_list_at_frontier(Receipt, Revision, Commands,
                                    Records, Errors),
       nb_setval(mettaclaw_command_batch_cache,
                 command_batch_frontier(Receipt, Turn, Commands,
                                        Records, Errors))
    ;  Records = [['COMMAND_BATCH_DEFERRED:',
                   "new input advanced the causal frontier"]],
       Errors = [[stale_frontier_nothing_ran, Commands,
                  "command batch deferred until current input is observed"]],
       nb_setval(mettaclaw_command_batch_cache,
                 command_batch_frontier(Receipt, Turn, Commands,
                                        Records, Errors))
    ), !.

receipt_current(Receipt, _Revision) :-
    catch('py-call'(['helper.receipt_current', Receipt], 1),
          _, fail).

'command-batch-errors'(Turn, Errors) :-
    ( nb_current(mettaclaw_command_batch_cache,
                 command_batch_frontier(_Receipt, CachedTurn, _Commands,
                                        _Records, CachedErrors)),
      CachedTurn == Turn
    -> copy_term(CachedErrors, Errors)
    ; nb_current(mettaclaw_command_batch_cache,
                 command_batch(CachedTurn, _Commands, _Records, CachedErrors)),
      CachedTurn == Turn
    -> copy_term(CachedErrors, Errors)
    ; Errors = []
    ), !.

run_command_list_once([], [], []).
run_command_list_once([Command|Rest], [Record|Records], Errors) :-
    run_command_once(Command, Record, CommandErrors),
    run_command_list_once(Rest, Records, RestErrors),
    append(CommandErrors, RestErrors, Errors).

run_command_list_at_frontier(_Receipt, _Revision, [], [], []).
run_command_list_at_frontier(Receipt, Revision, [Command|Rest],
                             [Record|Records], Errors) :-
    ( receipt_current(Receipt, Revision)
    -> run_command_once(Command, Record, CommandErrors),
       run_command_list_at_frontier(Receipt, Revision, Rest,
                                    Records, RestErrors),
       append(CommandErrors, RestErrors, Errors)
    ;  Record = ['COMMAND_DEFERRED_STALE_FRONTIER:', Command],
       Records = [],
       Errors = [[stale_frontier_nothing_ran, Command,
                  "remaining commands deferred after new input"]]
    ).

run_command_once(Command, ['COMMAND_RETURN:', [Command, Normalized]], Errors) :-
    catch(( once(eval(Command, Raw)) -> Status = ok(Raw)
                                    ; Status = failed ),
          Exception,
          Status = exception(Exception)),
    command_status(Status, Command, Value, Errors),
    normalize_command_value(Value, Normalized).

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
