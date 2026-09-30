"""Moving a widget from one layout to another without leaving PySide a dangling item.

``addWidget``/``insertWidget`` accept a widget that already sits in another
layout and quietly take it out of that one — Qt deletes the old
``QWidgetItem`` in C++. PySide is not told. If it had ever handed that item to
Python it still holds a wrapper registered at the item's address, and it goes
on answering for that address after the item is freed. PySide itself hands
items to Python without anyone asking: ``addLayout``/``setLayout`` walk the
nested layout with ``itemAt`` to set up ownership, so every widget in a row
added that way has a wrapper.

The stale wrapper is harmless until a *QObject* is allocated at the freed
address. Constructing it then asks PySide for the metaobject of the Python
object registered there, gets the layout item's type, which has none, and
dereferences NULL in ``SignalManager::retrieveMetaObject`` — an access
violation with nothing in the log, while creating whatever came next (a decode
``QThread`` when Play is pressed, a ``QEventLoop`` in a test). Measured under
cdb on PySide6 6.11.1; a 17-line reproduction crashed in under a second.

``removeWidget`` goes through PySide and invalidates the wrapper, so the fix is
to take the widget out explicitly before putting it anywhere else. Every
widget the app re-homes between layouts goes through :func:`detach_from_layout`
first.
"""

from __future__ import annotations

from PySide6.QtWidgets import QLayout, QWidget


def detach_from_layout(widget: QWidget) -> None:
    """Take *widget* out of whichever layout holds it, through PySide.

    A no-op for a widget no layout holds. Searches every layout under the
    parent, because the one holding it is often a row nested inside the
    parent's own layout. ``indexOf`` compares pointers, so the search never
    reads an item it did not already have.
    """
    parent = widget.parentWidget()
    if parent is None:
        return
    own = parent.layout()
    layouts = ([own] if own is not None else []) + parent.findChildren(QLayout)
    for layout in layouts:
        if layout.indexOf(widget) >= 0:
            layout.removeWidget(widget)
            return
