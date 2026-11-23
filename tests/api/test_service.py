"""Tests for api.service: the seam imports the reorganised converter layout directly."""

import ast
import inspect

import converter.actions.run
import converter.core.issues
import converter.files
import converter.tools.check
from api import service


def test_names_come_from_the_new_layout():
    """Re-exported names are the objects from the reorganised ``converter`` packages."""
    assert service.run_action is converter.actions.run.run_action
    assert service.issues is converter.core.issues
    assert service.settings_save_failed is converter.core.issues.settings_save_failed
    assert service.safe_destination is converter.files.safe_destination
    assert service.check_tools is converter.tools.check.check_tools


def test_no_guarded_imports():
    """No try/except around imports: a broken service-layer import must fail loudly (R8)."""
    tree = ast.parse(inspect.getsource(service))
    assert not [node for node in ast.walk(tree) if isinstance(node, ast.Try)]
