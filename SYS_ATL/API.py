from .prelude import *
from .LoopIR import UAST, LoopIR
from .LoopIR import T
from .typecheck import TypeChecker
from .LoopIR_compiler import Compiler, run_compile, compile_to_strings
from .LoopIR_interpreter import Interpreter, run_interpreter
from .LoopIR_scheduling import Schedules
from .LoopIR_scheduling import (name_plus_count,
                                iter_name_to_pattern,
                                nested_iter_names_to_pattern)
from .LoopIR_unification import DoReplace, UnificationError
from .effectcheck import InferEffects, CheckEffects

from .memory import Memory
from .configs import Config

from .pattern_match import match_pattern
from .parse_fragment import parse_fragment

import weakref
from weakref import WeakKeyDictionary


# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
#   proc provenance tracking

# every LoopIR.proc is either a root (not in this dictionary)
# or there is some other LoopIR.proc which is its root
_proc_root = WeakKeyDictionary()


def _proc_prov_eq(lhs, rhs):
    """ test whether two procs have the same provenance """
    lhs = lhs if lhs not in _proc_root else _proc_root[lhs]
    rhs = rhs if rhs not in _proc_root else _proc_root[rhs]
    assert lhs not in _proc_root and rhs not in _proc_root
    return lhs is rhs


# TODO: This is a terrible hack that should be replaced by
#       an actual Union Find data structure in the future
def _proc_prov_unify(lhs, rhs):
    # choose arbitrarily to reset the rhs root to refer to the lhs
    overwrite_set = [p() for p in _proc_root.keyrefs()]
    overwrite_set = [p for p in overwrite_set
                     if p and _proc_root[p] is rhs]
    for p in overwrite_set:
        _proc_root[p] = lhs
    _proc_root[rhs] = lhs

# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
#   iPython Display Object

class MarkDownBlob:
    def __init__(self, mkdwn_str):
        self.mstr = mkdwn_str

    def _repr_markdown_(self):
        return self.mstr

# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
#   Procedure Objects

def compile_procs(proc_list, path, c_file, h_file, malloc=False):
    assert isinstance(proc_list, list)
    assert all(type(p) is Procedure for p in proc_list)
    run_compile([ p._loopir_proc for p in proc_list ],
                path, c_file, h_file, malloc=malloc)


class Procedure:
    def __init__(self, proc, _testing=None, _provenance_eq_Procedure=None):
        if isinstance(proc, LoopIR.proc):
            self._loopir_proc = proc
        else:
            assert isinstance(proc, UAST.proc)

            self._uast_proc = proc
            if _testing != "UAST":
                self._loopir_proc = TypeChecker(proc).get_loopir()
                self._loopir_proc = InferEffects(self._loopir_proc).result()
                CheckEffects(self._loopir_proc)

        # find the root provenance
        parent = _provenance_eq_Procedure
        if parent is None:
            pass # this is a new root; done
        else:
            parent = parent._loopir_proc
            # if the provenance Procedure is not a root, find its root
            if parent in _proc_root:
                parent = _proc_root[parent]
            assert parent not in _proc_root
            # and then set this new proc's root
            _proc_root[self._loopir_proc] = parent

    def __str__(self):
        if hasattr(self,'_loopir_proc'):
            return str(self._loopir_proc)
        else:
            return str(self._uast_proc)

    def _repr_markdown_(self):
        return ("```python\n"+self.__str__()+"\n```")

    def INTERNAL_proc(self):
        return self._loopir_proc

    # -------------------------------- #
    #     introspection operations
    # -------------------------------- #

    def check_effects(self):
        self._loopir_proc = InferEffects(self._loopir_proc).result()
        CheckEffects(self._loopir_proc)

    def name(self):
        return self._loopir_proc.name

    def show_effects(self):
        return str(self._loopir_proc.eff)

    def show_effect(self, stmt_pattern):
        stmt        = self._find_stmt(stmt_pattern)
        return str(stmt.eff)

    def is_instr(self):
        return self._loopir_proc.instr != None

    def get_instr(self):
        return self._loopir_proc.instr

    # ---------------------------------------------- #
    #     execution / interpretation operations
    # ---------------------------------------------- #

    def show_c_code(self):
        return MarkDownBlob("```c\n"+self.c_code_str()+"\n```")

    def c_code_str(self):
        decls, defns = compile_to_strings("c_code_str", [self._loopir_proc])
        return defns

    def compile_c(self, directory, filename, malloc=False):
        run_compile([self._loopir_proc], directory,
                    (filename + ".c"), (filename + ".h"), malloc)

    def interpret(self, **kwargs):
        run_interpreter(self._loopir_proc, kwargs)

    # ------------------------------- #
    #     scheduling operations
    # ------------------------------- #

    def simplify(self):
        '''
        Simplify the code in the procedure body. Currently only performs
        constant folding
        '''
        p = self._loopir_proc
        p = Schedules.DoSimplify(p).result()
        return Procedure(p)

    def rename(self, name):
        if not is_valid_name(name):
            raise TypeError(f"'{name}' is not a valid name")
        p = self._loopir_proc
        p = LoopIR.proc( name, p.args, p.preds, p.body,
                         p.instr, p.eff, p.srcinfo )
        return Procedure(p, _provenance_eq_Procedure=self)

    def make_instr(self, instr):
        if type(instr) is not str:
            raise TypeError("expected an instruction macro "
                            "(Python string with {} escapes "
                            "as an argument")
        p = self._loopir_proc
        p = LoopIR.proc(p.name, p.args, p.preds, p.body,
                        instr, p.eff, p.srcinfo)
        return Procedure(p, _provenance_eq_Procedure=self)

    def unsafe_assert_eq(self, other_proc):
        if type(other_proc) is not Procedure:
            raise TypeError("expected a procedure as argument")
        _proc_prov_unify(self._loopir_proc, other_proc._loopir_proc)
        return self

    def partial_eval(self, *args):
        p = self._loopir_proc
        if len(args) > len(p.args):
            raise TypeError(f"expected no more than {len(p.args)} "
                            f"arguments, but got {len(args)}")
        p = Schedules.DoPartialEval(p, args).result()
        return Procedure(p)

    def set_precision(self, name, typ_abbreviation):
        name, count = name_plus_count(name)
        _shorthand = {
            'R':    T.R,
            'f32':  T.f32,
            'f64':  T.f64,
            'i8':   T.int8,
            'i32':  T.int32,
        }
        if typ_abbreviation in _shorthand:
            typ = _shorthand[typ_abbreviation]
        else:
            raise TypeError("expected second argument to set_precision() "
                            "to be a valid primitive type abbreviation")

        loopir = self._loopir_proc
        loopir = Schedules.SetTypAndMem(loopir, name, count,
                                        basetyp=typ).result()
        return Procedure(loopir, _provenance_eq_Procedure=self)

    def set_window(self, name, is_window):
        name, count = name_plus_count(name)
        if type(is_window) is not bool:
            raise TypeError("expected second argument to set_window() to "
                            "be a boolean")

        loopir = self._loopir_proc
        loopir = Schedules.SetTypAndMem(loopir, name, count,
                                        win=is_window).result()
        return Procedure(loopir, _provenance_eq_Procedure=self)

    def set_memory(self, name, memory_obj):
        name, count = name_plus_count(name)
        if type(memory_obj) is not Memory:
            raise TypeError("expected second argument to set_memory() to "
                            "be a Memory object")

        loopir = self._loopir_proc
        loopir = Schedules.SetTypAndMem(loopir, name, count,
                                        mem=memory_obj).result()
        return Procedure(loopir, _provenance_eq_Procedure=self)

    def _find_stmt(self, stmt_pattern, call_depth=2, default_match_no=0):
        body        = self._loopir_proc.body
        stmt_lists  = match_pattern(body, stmt_pattern,
                                    call_depth=call_depth,
                                    default_match_no=default_match_no)
        if len(stmt_lists) == 0 or len(stmt_lists[0]) == 0:
            raise TypeError("failed to find statement")
        elif default_match_no is None:
            return [ s[0] for s in stmt_lists ]
        else:
            return stmt_lists[0][0]

    def _find_callsite(self, call_site_pattern):
        call_stmt   = self._find_stmt(call_site_pattern, call_depth=3)
        if type(call_stmt) is not LoopIR.Call:
            raise TypeError("pattern did not describe a call-site")

        return call_stmt


    def bind_config(self, var_pattern, config, field):
        # Check if config and field are valid here
        if type(config) is not Config:
            raise TypeError("Did not pass a config object")
        if type(field) is not str:
            raise TypeError("Did not pass a config field string")
        if not config.has_field(field):
            raise TypeError(f"expected '{field}' to be a field "+
                            f"in config '{config.name()}'")

        body    = self._loopir_proc.body
        matches = match_pattern(body, var_pattern, call_depth=1)

        if not matches:
            raise TypeError("failed to find expression")
        # Can only bind single read atm. How to reason about scoping?
        if len(matches) != 1 or type(matches[0]) is not LoopIR.Read:
            raise TypeError(f"expected a single Read")

        # Check that the type of config field and read are the same
        if matches[0].type != config.lookup(field)[1]:
            raise TypeError(f"types of config and a read variable does"+
                             " not match")

        loopir = self._loopir_proc
        loopir = Schedules.DoBindConfig(loopir, config, field, matches[0]).result()

        return Procedure(loopir, _provenance_eq_Procedure=self)
    
    
    def configwrite_after(self, stmt_pattern, config, field, var_pattern):
        if type(config) is not Config:
            raise TypeError("Did not pass a config object")
        if type(field) is not str:
            raise TypeError("Did not pass a config field string")
        if not config.has_field(field):
            raise TypeError(f"expected '{field}' to be a field "+
                            f"in config '{config.name()}'")

        if type(var_pattern) is not str:
            raise TypeError("expected second argument to be a string var")

        stmt     = self._find_stmt(stmt_pattern)
        loopir   = self._loopir_proc
        var_expr = parse_fragment(loopir, var_pattern, stmt)
        assert isinstance(var_expr, LoopIR.expr)
        loopir   = Schedules.DoConfigWriteAfter(loopir, stmt, config, field, var_expr).result()

        return Procedure(loopir, _provenance_eq_Procedure=self)

    def inline_window(self, stmt_pattern):
        if type(stmt_pattern) is not str:
            raise TypeError("Did not pass a stmt string")

        stmt   = self._find_stmt(stmt_pattern, default_match_no=None)
        loopir = self._loopir_proc
        loopir = Schedules.DoInlineWindow(loopir, stmt[0]).result()

        return Procedure(loopir, _provenance_eq_Procedure=self)


    def split(self, split_var, split_const, out_vars,
              tail='guard', perfect=False):
        if type(split_var) is not str:
            raise TypeError("expected first arg to be a string")
        elif not is_pos_int(split_const):
            raise TypeError("expected second arg to be a positive integer")
        elif split_const == 1:
            raise TypeError("why are you trying to split by 1?")
        elif not isinstance(out_vars,list) and not isinstance(out_vars, tuple):
            raise TypeError("expected third arg to be a list or tuple")
        elif len(out_vars) != 2:
            raise TypeError("expected third arg list/tuple to have length 2")
        elif not all(is_valid_name(s) for s in out_vars):
            raise TypeError("expected third arg to be a list/tuple of two "+
                            "valid name strings")

        pattern     = iter_name_to_pattern(split_var)
        # default_match_no=None means match all
        stmts       = self._find_stmt(pattern, default_match_no=None)
        loopir      = self._loopir_proc
        for s in stmts:
            loopir  = Schedules.DoSplit(loopir, s, quot=split_const,
                                        hi=out_vars[0], lo=out_vars[1],
                                        tail=tail,
                                        perfect=perfect).result()
        return Procedure(loopir, _provenance_eq_Procedure=self)

    def delete_pass(self):
        loopir = self._loopir_proc
        loopir = Schedules.DoDeletePass(loopir).result()

        return Procedure(loopir, _provenance_eq_Procedure=self)

    def reorder_stmts(self, first_pat, second_pat):
        if type(first_pat) is not str:
            raise TypeError("expected first arg to be a pattern in string")
        if type(second_pat) is not str:
            raise TypeError("expected second arg to be a pattern in string")

        first_stmt = self._find_stmt(first_pat, default_match_no=None)
        second_stmt = self._find_stmt(second_pat, default_match_no=None)

        if not first_stmt or not second_stmt:
            raise TypeError("failed to find stmt")
        if len(first_stmt) != 1 or len(second_stmt) != 1:
            raise TypeError("expected stmt patterns to be specified s.t. it has "+
                            "only one matching")

        loopir = self._loopir_proc
        loopir = Schedules.DoReorderStmt(loopir, first_stmt[0], second_stmt[0]).result()

        return Procedure(loopir, _provenance_eq_Procedure=self)
        

    def reorder(self, out_var, in_var):
        if type(out_var) is not str:
            raise TypeError("expected first arg to be a string")
        elif not is_valid_name(in_var):
            raise TypeError("expected second arg to be a valid name string")

        pattern     = nested_iter_names_to_pattern(out_var, in_var)
        # default_match_no=None means match all
        stmts       = self._find_stmt(pattern, default_match_no=None)
        loopir      = self._loopir_proc
        for s in stmts:
            loopir  = Schedules.DoReorder(loopir, s).result()
        return Procedure(loopir, _provenance_eq_Procedure=self)

    def unroll(self, unroll_var):
        if type(unroll_var) is not str:
            raise TypeError("expected first arg to be a string")

        pattern     = iter_name_to_pattern(unroll_var)
        # default_match_no=None means match all
        stmts       = self._find_stmt(pattern, default_match_no=None)
        loopir      = self._loopir_proc
        for s in stmts:
            loopir  = Schedules.DoUnroll(loopir, s).result()
        return Procedure(loopir, _provenance_eq_Procedure=self)

    def replace(self, subproc, pattern):
        if type(subproc) is not Procedure:
            raise TypeError("expected first arg to be a subprocedure")
        elif type(pattern) is not str:
            raise TypeError("expected second arg to be a string")

        body        = self._loopir_proc.body
        stmt_lists  = match_pattern(body, pattern, call_depth=1)
        if len(stmt_lists) == 0:
            raise TypeError("failed to find statement")

        loopir = self._loopir_proc
        for stmt_block in stmt_lists:
            loopir = DoReplace(loopir, subproc._loopir_proc,
                               stmt_block).result()

        return Procedure(loopir, _provenance_eq_Procedure=self)

    def replace_all(self, subproc):
        # TODO: this is a bad implementation, but necessary due to issues in the
        #       implementation of replace above: after a replacement, statements
        #       can be moved in memory, so matches are invalidated. Matching and
        #       replacing ought to be fused instead. This directive would reduce
        #       to a flag on the find/replace.
        assert isinstance(subproc, Procedure)
        assert len(subproc._loopir_proc.body) == 1, \
            "Compound statements not supported"

        patterns = {
            LoopIR.Assign     : '_ = _',
            LoopIR.Reduce     : '_ += _',
            LoopIR.WriteConfig: 'TODO',
            LoopIR.Pass       : 'TODO',
            LoopIR.If         : 'TODO',
            LoopIR.ForAll     : 'for _ in _: _',
            LoopIR.Seq        : 'TODO',
            LoopIR.Alloc      : 'TODO',
            LoopIR.Free       : 'TODO',
            LoopIR.Call       : 'TODO',
            LoopIR.WindowStmt : 'TODO',
        }

        pattern = patterns[type(subproc._loopir_proc.body[0])]

        proc = self
        i = 0
        while True:
            try:
                proc = proc.replace(subproc, f'{pattern} #{i}')
            except TypeError as e:
                if 'failed to find statement' in str(e):
                    return proc
                raise
            except UnificationError:
                i += 1

    def inline(self, call_site_pattern):
        call_stmt = self._find_callsite(call_site_pattern)

        loopir = self._loopir_proc
        loopir = Schedules.DoInline(loopir, call_stmt).result()
        return Procedure(loopir, _provenance_eq_Procedure=self)

    def call_eqv(self, other_Procedure, call_site_pattern):
        call_stmt = self._find_callsite(call_site_pattern)

        old_proc    = call_stmt.f
        new_proc    = other_Procedure._loopir_proc
        if not _proc_prov_eq(old_proc, new_proc):
            raise TypeError("the procedures were not equivalent")

        loopir      = self._loopir_proc
        loopir      = Schedules.DoCallSwap(loopir, call_stmt,
                                                   new_proc).result()
        return Procedure(loopir, _provenance_eq_Procedure=self)

    def bind_expr(self, new_name, expr_pattern, cse=False):
        if not is_valid_name(new_name):
            raise TypeError("expected first argument to be a valid name")
        body    = self._loopir_proc.body
        matches = match_pattern(body, expr_pattern, call_depth=1)

        if not matches:
            raise TypeError("failed to find expression")

        if any(not isinstance(m, LoopIR.expr) for m in matches):
            raise TypeError("pattern matched, but not to an expression")

        if any(not m.type.is_numeric() for m in matches):
            raise TypeError("only numeric (not index or size) expressions "+
                            "can be targeted by bind_expr()")

        loopir = self._loopir_proc
        loopir = Schedules.DoBindExpr(loopir, new_name, matches, cse).result()
        return Procedure(loopir, _provenance_eq_Procedure=self)

    def stage_assn(self, new_name, stmt_pattern):
        if not is_valid_name(new_name):
            raise TypeError("expected first argument to be a valid name")

        ir = self._loopir_proc
        matches = match_pattern(ir.body, stmt_pattern, call_depth=1,
                                default_match_no=0)
        if not matches:
            raise ValueError("failed to find Assign or Reduce")

        for match in matches:
            if isinstance(match, list) and len(match) == 1:
                match = match[0]
            if not isinstance(match, (LoopIR.Assign, LoopIR.Reduce)):
                raise ValueError(f"expected Assign or Reduce, got {match}")
            ir = Schedules.DoStageAssn(ir, new_name, match).result()

        return Procedure(ir, _provenance_eq_Procedure=self)

    def par_to_seq(self, par_pattern):
        par_stmts = self._find_stmt(par_pattern, default_match_no=None)
        loopir   = self._loopir_proc
        for s in par_stmts:
            if type(s) is not LoopIR.ForAll:
                raise TypeError("pattern did not describe a par loop")

            loopir  = Schedules.DoParToSeq(loopir, s).result()

        return Procedure(loopir, _provenance_eq_Procedure=self)


    def lift_alloc(self, alloc_site_pattern, n_lifts=1, mode='row', size=None,
                   keep_dims=False):
        if not is_pos_int(n_lifts):
            raise TypeError("expected second argument 'n_lifts' to be "
                            "a positive integer")
        if type(mode) is not str:
            raise TypeError("expected third argument 'mode' to be "
                            "'row' or 'col'")
        if size and type(size) is not int:
            raise TypeError("expected fourth argument 'size' to be "
                            "an integer")

        alloc_stmts = self._find_stmt(alloc_site_pattern, default_match_no=None)
        loopir      = self._loopir_proc
        for s in alloc_stmts:
            if type(s) is not LoopIR.Alloc:
                raise TypeError("pattern did not describe an alloc statement")

            loopir  = Schedules.DoLiftAlloc(
                loopir, s, n_lifts, mode, size, keep_dims).result()

        return Procedure(loopir, _provenance_eq_Procedure=self)

    def fission_after(self, stmt_pattern, n_lifts=1):
        if not is_pos_int(n_lifts):
            raise TypeError("expected second argument 'n_lifts' to be "
                            "a positive integer")

        stmts        = self._find_stmt(stmt_pattern, default_match_no=None)
        loopir      = self._loopir_proc
        for s in stmts:
            loopir      = Schedules.DoFissionLoops(loopir, s,
                                                   n_lifts).result()
        return Procedure(loopir, _provenance_eq_Procedure=self)

    def factor_out_stmt(self, name, stmt_pattern):
        if not is_valid_name(name):
            raise TypeError("expected first argument to be a valid name")
        stmt        = self._find_stmt(stmt_pattern)

        loopir          = self._loopir_proc
        passobj         = Schedules.DoFactorOut(loopir, name, stmt)
        loopir, subproc = passobj.result(), passobj.subproc()
        return ( Procedure(loopir, _provenance_eq_Procedure=self),
                 Procedure(subproc) )

# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
