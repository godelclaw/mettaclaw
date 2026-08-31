:- use_module(library(process)).
:- use_module(library(readutil)).

:- dynamic native_iter_source_directory/1.
:- prolog_load_context(directory, NativeIterSourceDirectory),
   asserta(native_iter_source_directory(NativeIterSourceDirectory)).

native_iter_text_atom(Value, Atom) :- atom(Value), !, Atom = Value.
native_iter_text_atom(Value, Atom) :- string(Value), !, atom_string(Atom, Value).

native_iter_configured_directory(default, Directory) :- !,
    ( getenv('METTACLAW_ITER_PROCESS_DIR', Configured)
      -> native_iter_absolute_path(Configured, Directory)
       ; native_iter_absolute_path('memory/transformations', Directory) ).
native_iter_configured_directory(Value, Directory) :-
    native_iter_text_atom(Value, Path),
    native_iter_absolute_path(Path, Directory).

native_iter_absolute_path(Path, Absolute) :-
    ( is_absolute_file_name(Path)
      -> Absolute = Path
       ; working_directory(Current, Current),
         directory_file_path(Current, Path, Absolute) ).

native_iter_entry_name(Name) :-
    \+ sub_atom(Name, 0, 1, _, '_'),
    file_name_extension(_, metta, Name).

native_iter_capture(Directory, Captured) :-
    ( exists_directory(Directory)
      -> directory_files(Directory, Entries),
         include(native_iter_entry_name, Entries, Active0),
         sort(Active0, Active),
         maplist(native_iter_capture_entry(Directory), Active, Captured)
       ; Captured = [] ).

native_iter_capture_entry(Directory, Name, captured(Name, Source)) :-
    directory_file_path(Directory, Name, Path),
    setup_call_cleanup(
        open(Path, read, Stream, [encoding(utf8)]),
        read_string(Stream, _, Source),
        close(Stream)).

native_iter_runner(Runner) :-
    getenv('METTACLAW_PETTA_RUNNER', Configured),
    native_iter_text_atom(Configured, Runner),
    exists_file(Runner),
    !.
native_iter_runner(_) :-
    throw(error(existence_error(file, 'METTACLAW_PETTA_RUNNER'), _)).

native_iter_main(Main) :-
    native_iter_runner(Runner),
    file_directory_name(Runner, Root),
    directory_file_path(Root, 'src/main.pl', Main),
    exists_file(Main),
    !.
native_iter_main(_) :-
    throw(error(existence_error(file, 'PeTTa src/main.pl'), _)).

native_iter_timeout(Seconds) :-
    ( getenv('METTACLAW_ITER_PROCESS_TIMEOUT_SECONDS', Raw),
      catch(atom_number(Raw, Parsed), _, fail),
      Parsed > 0
      -> Seconds is Parsed
       ; Seconds = 5.0 ).

native_iter_temporary_path(Tag, Suffix, Path) :-
    tmp_file(Tag, Base),
    atom_concat(Base, Suffix, Path).

native_iter_write_source(Path, Source) :-
    setup_call_cleanup(
        open(Path, write, Stream, [encoding(utf8)]),
        write(Stream, Source),
        close(Stream)).

native_iter_write_term(Path, Term) :-
    setup_call_cleanup(
        open(Path, write, Stream, [encoding(utf8)]),
        write_term(Stream, Term,
                   [ quoted(true), ignore_ops(true), numbervars(true),
                     fullstop(true), nl(true) ]),
        close(Stream)).

native_iter_delete_if_present(Path) :-
    ( exists_file(Path) -> delete_file(Path) ; true ).

native_iter_wait(Pid, Status) :-
    native_iter_timeout(Seconds),
    get_time(Now),
    Deadline is Now + Seconds,
    native_iter_poll(Pid, Deadline, Status).

native_iter_poll(Pid, Deadline, Status) :-
    process_wait(Pid, Initial, [timeout(0)]),
    ( Initial \== timeout
      -> Status = Initial
       ; get_time(Now),
         ( Now >= Deadline
           -> catch(process_kill(Pid, term), _, true),
              process_wait(Pid, _, []),
              Status = timeout
            ; sleep(0.01),
              native_iter_poll(Pid, Deadline, Status) ) ).

native_iter_result_term(Path, Term) :-
    setup_call_cleanup(
        open(Path, read, Stream, [encoding(utf8)]),
        read_term(Stream, Term, []),
        close(Stream)).

native_iter_detail(Path, Detail) :-
    ( catch(read_file_to_string(Path, Text, [encoding(utf8)]), _, fail)
      -> string_length(Text, Length),
         Keep is min(500, Length),
         sub_string(Text, 0, Keep, _, Detail)
       ; Detail = "" ).

native_iter_tail_detail(Path, Detail) :-
    ( catch(read_file_to_string(Path, Text, [encoding(utf8)]), _, fail)
      -> string_length(Text, Length),
         Keep is min(300, Length),
         Start is Length - Keep,
         sub_string(Text, Start, Keep, 0, Detail)
       ; Detail = "" ).

native_iter_worker_path(Worker) :-
    native_iter_source_directory(SourceDirectory),
    directory_file_path(SourceDirectory, 'native_iter_worker.metta', Worker).

native_iter_invoke(captured(_, Source), Visible, Outcome, Detail) :-
    native_iter_main(Main),
    native_iter_worker_path(Worker),
    native_iter_temporary_path(native_iter_transform, '.metta', TransformPath),
    native_iter_temporary_path(native_iter_visible, '.term', VisiblePath),
    native_iter_temporary_path(native_iter_result, '.term', ResultPath),
    native_iter_temporary_path(native_iter_stdout, '.txt', StdoutPath),
    native_iter_temporary_path(native_iter_stderr, '.txt', StderrPath),
    setup_call_cleanup(
        ( native_iter_write_source(TransformPath, Source),
          native_iter_write_term(VisiblePath, Visible) ),
        native_iter_launch(
            Main, Worker, TransformPath, VisiblePath, ResultPath,
            StdoutPath, StderrPath, Outcome, Detail),
        ( native_iter_delete_if_present(TransformPath),
          native_iter_delete_if_present(VisiblePath),
          native_iter_delete_if_present(ResultPath),
          native_iter_delete_if_present(StdoutPath),
          native_iter_delete_if_present(StderrPath) )).

native_iter_launch(
    Main, Worker, TransformPath, VisiblePath, ResultPath,
    StdoutPath, StderrPath, Outcome, Detail) :-
    catch(
        setup_call_cleanup(
            ( open(StdoutPath, write, Stdout, [encoding(utf8)]),
              open(StderrPath, write, Stderr, [encoding(utf8)]) ),
            ( process_create(
                  path(swipl),
                  [ '-q', '-s', Main, '--',
                    Worker, TransformPath, VisiblePath, ResultPath,
                    '--silent' ],
                  [ process(Pid),
                    stdin(null),
                    stdout(stream(Stdout)),
                    stderr(stream(Stderr)) ]),
              native_iter_wait(Pid, Status) ),
            ( close(Stdout), close(Stderr) )),
        Error,
        ( message_to_string(Error, Message),
          Outcome = failure,
          Detail = Message )),
    ( var(Pid)
      -> true
       ; native_iter_interpret(
           Status, ResultPath, StdoutPath, StderrPath, Outcome, Detail) ).

native_iter_interpret(timeout, _, _, _, failure, "timeout") :- !.
native_iter_interpret(
    exit(0), ResultPath, StdoutPath, StderrPath, Outcome, Detail) :-
    !,
    catch(
        native_iter_result_term(ResultPath, Term),
        Error,
        ( message_to_string(Error, ReadError), Term = read_failure )),
    ( Term == read_failure
      -> Outcome = failure,
         native_iter_detail(StdoutPath, StdoutText),
         native_iter_tail_detail(StderrPath, StderrText),
         format(string(Detail), '~s; stdout: ~s; stderr: ~s',
                [ReadError, StdoutText, StderrText])
       ; native_iter_worker_result(Term, Outcome, Detail) ),
    ( var(Detail) -> native_iter_detail(StderrPath, Detail) ; true ).
native_iter_interpret(Status, _, StdoutPath, StderrPath, failure, Detail) :-
    native_iter_detail(StdoutPath, OutputText),
    native_iter_tail_detail(StderrPath, ErrorText),
    format(string(Detail), '~w; stdout: ~s; stderr: ~s',
           [Status, OutputText, ErrorText]).

native_iter_worker_result(
    ['native-iter-worker-results', [[success, NextVisible]]],
    success(NextVisible), "") :-
    NextVisible = ['coding-view', _, _],
    !.
native_iter_worker_result(
    ['native-iter-worker-results', [failure]], failure, "transformation failed") :-
    !.
native_iter_worker_result(Term, failure, Detail) :-
    swrite(Term, Source),
    string_length(Source, Length),
    Keep is min(500, Length),
    sub_string(Source, 0, Keep, _, Prefix),
    format(string(Detail), 'malformed transformation result: ~s', [Prefix]).

native_iter_run([], Visible, Visible, 'iter-observations-empty').
native_iter_run(
    [Captured|Rest], Visible0, Visible,
    ['iter-observation-list', Observation, Observations]) :-
    Captured = captured(Name, _),
    catch(
        native_iter_invoke(Captured, Visible0, Outcome, Detail),
        Error,
        ( message_to_string(Error, Detail), Outcome = failure )),
    ( Outcome = success(Visible1)
      -> Observation = ['iter-observation', Name, success, ""],
         Next = Visible1
       ; Observation = ['iter-observation', Name, failure, Detail],
         Next = Visible0 ),
    native_iter_run(Rest, Next, Visible, Observations).

native_iter_failure(Visible, Error, Result) :-
    message_to_string(Error, Detail),
    Result = [
        'iter-native-result', Visible,
        ['iter-observation-list',
         ['iter-observation', adapter, failure, Detail],
         'iter-observations-empty']
    ].

'iter-native-run'(DirectoryValue, Visible, Result) :-
    catch(
        ( native_iter_configured_directory(DirectoryValue, Directory),
          native_iter_capture(Directory, Captured),
          native_iter_run(Captured, Visible, NextVisible, Observations),
          Result = ['iter-native-result', NextVisible, Observations] ),
        Error,
        native_iter_failure(Visible, Error, Result)),
    !.
