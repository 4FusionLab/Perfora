# SPDX-License-Identifier: GPL-3.0-only
"""Numeric expressions over native string inputs, including observable blanks.

Fusion's ValueCommandInput exposes its last valid expression when the visible
editor is empty, and does not fire inputChanged for that edit. String inputs
expose the actual text; a hidden native value input evaluates units/parameters.
"""
import math


class NumericInput:
    def __init__(self, control, evaluator, session, default, unit='', integer_bounds=None):
        self._control = control
        self._evaluator = evaluator
        self._session = session
        self._evaluated_expression = None
        self._expression_valid = False
        self.default_expression = default
        self.unit = unit
        self.integer_bounds = integer_bounds

    def __getattr__(self, name):
        return getattr(self._control, name)

    def __setattr__(self, name, value):
        if name.startswith('_') or name in ('default_expression', 'unit', 'integer_bounds') or hasattr(type(self), name):
            object.__setattr__(self, name, value)
        else:
            setattr(self._control, name, value)

    @property
    def expression(self):
        return self._control.value

    @expression.setter
    def expression(self, expression):
        self._control.value = str(expression)

    @property
    def value(self):
        expression = self.expression.strip()
        if not expression:
            raise ValueError('Check the value of ' + self.name + '.')
        if expression != self._evaluated_expression:
            self._evaluated_expression = expression
            self._expression_valid = False
            previous = self._session.updating
            self._session.updating = True
            try:
                self._evaluator.expression = expression
                self._expression_valid = self._evaluator.isValidExpression
            except RuntimeError:
                pass  # Native setters reject invalid text; keep it in the visible field.
            finally:
                self._session.updating = previous
        if not self._expression_valid or not self._evaluator.isValidExpression:
            raise ValueError('Check the value of ' + self.name + '.')
        value = self._evaluator.value
        if not math.isfinite(value):
            raise ValueError('Enter a finite value for ' + self.name + '.')
        if self.integer_bounds:
            low, high = self.integer_bounds
            if not value.is_integer() or not low <= value <= high:
                raise ValueError('%s must be an integer between %d and %d.' % (self.name, low, high))
            return int(value)
        return value

    @value.setter
    def value(self, value):
        # Callers use Fusion's internal cm/rad, just as with ValueCommandInput.
        suffix = {'mm': ' cm', 'deg': ' rad'}.get(self.unit, '')
        self.expression = str(value) + suffix

    @property
    def isValidExpression(self):
        try:
            self.value
            return True
        except (ValueError, RuntimeError, OverflowError):
            return False

    @property
    def model_expression(self):
        # Preserve parameters/equations while making implicit mm/deg explicit
        # before handing an expression to Extrude in a differently sized document.
        if self.isValidExpression:
            return self._evaluator.expression
        return self.expression  # Hidden optional fields are validated when used.
