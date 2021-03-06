# -*- coding: utf-8 -*-
###########################################################################
#    Copyright (C) 2008 by Andrew Mahone
#    <andrew.mahone@gmail.com>
#
# Copyright: See COPYING file that comes with this distribution
#
###########################################################################
import os.path
import re
import codecs
from RestrictedPython.RCompile import RExpression
from RestrictedPython.MutatingWalker import walk
from RestrictedPython.Guards import safe_builtins as eval_builtins
from string import maketrans
from compiler import ast, parse

_subexpr = re.compile("\$\$|\$\$|\$(?P<nosan>/)?(?P<label>[a-z]+)?(?P<paren>\()?")

pathseptrans = dict(enumerate(unicode(maketrans('/', '_')[:48])))
pathtrans = dict(enumerate(unicode(maketrans(r'/\[]?=+<>;",*|', os.path.sep + '_' * 13)[:125])))

eval_builtins = eval_builtins.copy()
eval_builtins.update(filter=filter, map=map, max=max, min=min, reduce=reduce, reversed=reversed, slice=slice, sorted=sorted)
del eval_builtins['delattr']
del eval_builtins['setattr']
eval_globals = {'__builtins__':eval_builtins, '_getattr_':getattr, '_getitem_': lambda x, y: x[y]}

def underscorereplace_errors(e):
    return (u'_' * (e.end - e.start), e.end)

codecs.register_error('underscorereplace', underscorereplace_errors)

def evaluate(item, cdict):
    if isinstance(item, Expr):
        return item.evaluate(cdict)
    else:
        return item

class InlineFuncsVisitor:
    def __init__(self, filename, baseexpr):
        self.filename = filename
        self.baseexpr = baseexpr
    def visitCallFunc(self, node, *args):
        if not hasattr(node, 'node'):
            return node
        if not isinstance(node.node, ast.Name):
            return node
        handler = getattr(self, '_' + node.node.name, None)
        if handler:
            return handler(node, *args)
        else:
            return node
    def _first(self, node, *args):
        clocals = ast.Const(locals)
        clocals.lineno = node.lineno
        clocals = ast.CallFunc(clocals, [], None, None)
        clocals.lineno = node.lineno
        exp = ast.Or([])
        exp.lineno = node.lineno
        for item in node.args:
            if not isinstance(item, ast.Const) or isinstance(item.value, basestring):
                if isinstance(item, ast.Const):
                    item = item.value
                item = self.baseexpr(item, self.filename)
                item = ast.Const(item.evaluate)
                item.lineno = node.lineno
                item = ast.CallFunc(item, [clocals])
                item.lineno = node.lineno
            exp.nodes.append(item)
        return exp

class Expr(RExpression, object):
    _globals = eval_globals
    _cache = {}

    def __new__(cls, source, filename="", baseexpr=None):
        key = (cls, source, filename, baseexpr)
        if isinstance(source, basestring):
            if key not in cls._cache:
                cls._cache[key] = object.__new__(cls)
            return cls._cache[key]
        elif isinstance(source, ast.Node):
            return object.__new__(cls)
        elif isinstance(source, cls):
            return source

    def __init__(self, source, filename="", baseexpr=None):
        if hasattr(self, '_compiled'):
            return
        self._source = source
        self._baseexpr = baseexpr or getattr(self.__class__, '_baseexpr', None) or self.__class__
        self._filename = filename
        if not isinstance(source, ast.Node):
            RExpression.__init__(self, source, filename)
            source = self._get_tree()
        else:
            if not (isinstance(source, ast.Expression)):
                source = ast.Expression(source)
            source.filename = filename
            walk(source, InlineFuncsVisitor(self._filename, self._baseexpr))
        gen = self.CodeGeneratorClass(source)
        self._compiled = gen.getCode()

    def __hash__(self):
        return hash(self._compiled)

    def _get_tree(self):
        tree = RExpression._get_tree(self)
        walk(tree, InlineFuncsVisitor(self.filename, self._baseexpr))
        return tree

    def evaluate(self, cdict):
        try:
            return eval(self._compiled, self._globals, cdict)
        except NameError:
            return None

class StringExpr(Expr):
    def evaluate(self, cdict):
        ret = super(self.__class__, self).evaluate(cdict)
        if ret is not None:
            ret = unicode(ret)
        return ret

class SanitizedExpr(Expr):
    def evaluate(self, cdict):
        ret = super(self.__class__, self).evaluate(cdict)
        if ret is not None:
            ret = unicode(ret).translate(pathseptrans)
        return ret

class Format(Expr):
    _sanitize = False

    def _get_tree(self):
        clocals = ast.Const(locals)
        clocals.lineno = 1
        clocals = ast.CallFunc(clocals, [], None, None)
        clocals.lineno = 1
        items = self._parse()
        te = ast.Tuple([])
        te.lineno = 1
        ta = ast.Tuple([])
        ta.lineno = 1
        for item in items:
            if isinstance(item, Expr):
                item = ast.Const(item.evaluate)
                item.lineno = 1
                item = ast.CallFunc(item, [clocals])
                item.lineno = 1
                ta.nodes.append(item)
                te.nodes.append(item)
            else:
                item = ast.Const(item)
                item.lineno = 1
                ta.nodes.append(item)
        result = ast.Const(''.join)
        result.lineno = 1
        result = ast.CallFunc(result, [ta], None, None)
        if te.nodes:
            none = ast.Name('None')
            none.lineno = 1
            test = ast.Compare(none, [('in', te)])
            test.lineno = 1
            result = ast.IfExp(test, none, result)
            result.lineno = 1
        result = ast.Expression(result)
        result.lineno = 1
        result.filename = self._filename
        return result

    def _parse(self):
        state = []
        result = []
        cur = []
        prevend = 0
        while 1:
            m = _subexpr.search(self._source, prevend)
            if not m:
                cur.append(self._source[prevend:])
                break
            mt = m.group(0)
            mg = m.groupdict()
            if m.start() > prevend:
                cur.append(self._source[prevend:m.start()])
            prevend = m.end()
            if mt == '$$':
                cur.append('$')
            else:
                if any(cur):
                    result.append(''.join(cur))
                cur = []
                expr_class = StringExpr if mg['nosan'] or not self._sanitize else SanitizedExpr
                if not mg['paren']:
                    result.append(expr_class(mg['label'], self._filename, self._baseexpr))
                else:
                    expr_text = self._source[prevend:]
                    try:
                        parse(expr_text, 'eval')
                    except SyntaxError, e:
                        prevend += e.offset
                        expr_text = expr_text[:e.offset-1]
                        if mg['label']:
                            expr_text = "%s(%s)" % (mg['label'], expr_text)
                        result.append(expr_class(expr_text, self._filename, self._baseexpr))
                    else:
                        start = m.start()
                        raise SyntaxError('Unexpected EOF while parsing', (None, 1, len(self._source) - start, self._source[start:]))
        if any(cur):
            result.append(''.join(cur))
        return result

class SanitizedFormat(Format):
    _sanitize = True

class FileFormat(SanitizedFormat):
    _baseexpr = SanitizedFormat
    def evaluate(self, cdict):
        ret = super(self.__class__, self).evaluate(cdict)
        if ret is not None:
            ret = ret.translate(pathtrans)
        return ret

#class Format(Expr):

def unique(testset, expr, evalexpr): pass

__all__ = ['Format', 'FileFormat', 'Expr', 'evaluate']
