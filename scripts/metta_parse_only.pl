:- use_module(library(readutil)).

:- initialization(main, main).

main :-
    current_prolog_flag(argv, [PettaRoot, Candidate|_]),
    directory_file_path(PettaRoot, 'src/parser.pl', Parser),
    directory_file_path(PettaRoot, 'src/filereader.pl', FileReader),
    catch(
        ( load_files([Parser, FileReader], [silent(true)]),
          parse_only_file(Candidate)
        ),
        Error,
        ( message_to_string(Error, Message),
          format(user_error, '~s~n', [Message]),
          halt(2)
        )
    ),
    halt(0).
main :-
    format(user_error, 'usage: metta_parse_only.pl PETTA_ROOT CANDIDATE~n', []),
    halt(2).

parse_only_file(Filename) :-
    read_file_to_string(Filename, Source, []),
    string_codes(Source, SourceCodes),
    strip(SourceCodes, 0, Codes),
    phrase(top_forms(Forms, 1), Codes),
    maplist(read_form_only, Forms).

read_form_only(Form) :-
    arg(1, Form, Source),
    sread(Source, _).
