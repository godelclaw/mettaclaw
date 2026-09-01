native_iter_read_visible(PathValue, Term) :-
    ( atom(PathValue) -> Path = PathValue ; atom_string(Path, PathValue) ),
    setup_call_cleanup(
        open(Path, read, Stream, [encoding(utf8)]),
        read_term(Stream, Term, []),
        close(Stream)).

native_iter_write_result(PathValue, Term) :-
    ( atom(PathValue) -> Path = PathValue ; atom_string(Path, PathValue) ),
    setup_call_cleanup(
        open(Path, write, Stream, [encoding(utf8)]),
        write_term(Stream, Term,
                   [ quoted(true), ignore_ops(true), numbervars(true),
                     fullstop(true), nl(true) ]),
        close(Stream)).
