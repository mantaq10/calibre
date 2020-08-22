#!/usr/bin/env python2
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from __future__ import absolute_import, division, print_function, unicode_literals

import os
from textwrap import fill

from PyQt5.Qt import (
    QApplication, QCheckBox, QComboBox, QCursor, QFont, QHBoxLayout, QIcon, QLabel,
    QPalette, QPushButton, QSize, QSplitter, Qt, QTextBrowser, QToolButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget, pyqtSignal
)

from calibre import prepare_string_for_xml
from calibre.ebooks.metadata import authors_to_string, fmt_sidx
from calibre.gui2 import Application, config, gprefs
from calibre.gui2.viewer.search import ResultsDelegate, SearchBox
from calibre.gui2.widgets2 import Dialog


def current_db():
    from calibre.gui2.ui import get_gui
    return (getattr(current_db, 'ans', None) or get_gui().current_db).new_api


def annotation_title(atype, singular=False):
    if singular:
        return {'bookmark': _('Bookmark'), 'highlight': _('Highlight')}.get(atype, atype)
    return {'bookmark': _('Bookmarks'), 'highlight': _('Highlights')}.get(atype, atype)


class BusyCursor(object):

    def __enter__(self):
        QApplication.setOverrideCursor(QCursor(Qt.WaitCursor))

    def __exit__(self, *args):
        QApplication.restoreOverrideCursor()


class AnnotsResultsDelegate(ResultsDelegate):

    add_ellipsis = False

    def result_data(self, result):
        if not isinstance(result, dict):
            return None, None, None, None
        full_text = result['text'].replace('0x1f', ' ')
        parts = full_text.split('\x1d')
        before = after = ''
        if len(parts) > 2:
            before, text = parts[:2]
            after = ' '.join(parts[2:]).replace('\x1d', '')
        elif len(parts) == 2:
            before, text = parts
        else:
            text = parts[0]
        return False, before, text, after


class ResultsList(QTreeWidget):

    current_result_changed = pyqtSignal(object)
    open_annotation = pyqtSignal(object)

    def __init__(self, parent):
        QTreeWidget.__init__(self, parent)
        self.setHeaderHidden(True)
        self.delegate = AnnotsResultsDelegate(self)
        self.setItemDelegate(self.delegate)
        self.section_font = QFont(self.font())
        self.itemDoubleClicked.connect(self.item_activated)
        self.section_font.setItalic(True)
        self.currentItemChanged.connect(self.current_item_changed)
        self.number_of_results = 0
        self.item_map = []

    def item_activated(self, item):
        r = item.data(0, Qt.UserRole)
        if isinstance(r, dict):
            self.open_annotation.emit(r['annotation'])

    def set_results(self, results):
        self.clear()
        self.number_of_results = 0
        self.item_map = []
        book_id_map = {}
        db = current_db()
        for result in results:
            book_id = result['book_id']
            if book_id not in book_id_map:
                book_id_map[book_id] = {'title': db.field_for('title', book_id), 'matches': []}
            book_id_map[book_id]['matches'].append(result)
        for book_id, entry in book_id_map.items():
            section = QTreeWidgetItem([entry['title']], 1)
            section.setFlags(Qt.ItemIsEnabled)
            section.setFont(0, self.section_font)
            self.addTopLevelItem(section)
            section.setExpanded(True)
            for result in entry['matches']:
                item = QTreeWidgetItem(section, [' '], 2)
                self.item_map.append(item)
                item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemNeverHasChildren)
                item.setData(0, Qt.UserRole, result)
                item.setData(0, Qt.UserRole + 1, self.number_of_results)
                self.number_of_results += 1
        if self.item_map:
            self.setCurrentItem(self.item_map[0])

    def current_item_changed(self, current, previous):
        if current is not None:
            r = current.data(0, Qt.UserRole)
            if isinstance(r, dict):
                self.current_result_changed.emit(r)
        else:
            self.current_result_changed.emit(None)

    def show_next(self, backwards=False):
        item = self.currentItem()
        if item is None:
            return
        i = int(item.data(0, Qt.UserRole + 1))
        i += -1 if backwards else 1
        i %= self.number_of_results
        self.setCurrentItem(self.item_map[i])

    def keyPressEvent(self, ev):
        key = ev.key()
        if key == Qt.Key_Down:
            self.show_next()
            return
        if key == Qt.Key_Up:
            self.show_next(backwards=True)
            return
        return QTreeWidget.keyPressEvent(self, ev)


class Restrictions(QWidget):

    restrictions_changed = pyqtSignal()

    def __init__(self, parent):
        QWidget.__init__(self, parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(QLabel(_('Restrict to') + ': '))
        la = QLabel(_('Types:'))
        h.addWidget(la)
        self.types_box = tb = QComboBox(self)
        tb.la = la
        tb.currentIndexChanged.connect(self.restrictions_changed)
        connect_lambda(tb.currentIndexChanged, tb, lambda tb: gprefs.set('browse_annots_restrict_to_type', tb.currentData()))
        la.setBuddy(tb)
        tb.setToolTip(_('Show only annotations of the specified type'))
        h.addWidget(tb)
        la = QLabel(_('User:'))
        h.addWidget(la)
        self.user_box = ub = QComboBox(self)
        ub.la = la
        ub.currentIndexChanged.connect(self.restrictions_changed)
        connect_lambda(ub.currentIndexChanged, ub, lambda ub: gprefs.set('browse_annots_restrict_to_user', ub.currentData()))
        la.setBuddy(ub)
        ub.setToolTip(_('Show only annotations created by the specified user'))
        h.addWidget(ub)
        h.addStretch(10)

    def re_initialize(self, db):
        tb = self.types_box
        before = tb.currentData()
        if not before:
            before = gprefs['browse_annots_restrict_to_type']
        tb.blockSignals(True)
        tb.clear()
        tb.addItem(' ', ' ')
        for atype in db.all_annotation_types():
            tb.addItem(annotation_title(atype), atype)
        if before:
            row = tb.findData(before)
            if row > -1:
                tb.setCurrentIndex(row)
        tb.blockSignals(False)
        tb_is_visible = tb.count() > 2
        tb.setVisible(tb_is_visible), tb.la.setVisible(tb_is_visible)
        tb = self.user_box
        before = tb.currentData()
        if not before:
            before = gprefs['browse_annots_restrict_to_user']
        tb.blockSignals(True)
        tb.clear()
        tb.addItem(' ', ' ')
        for user_type, user in db.all_annotation_users():
            q = '{}: {}'.format(user_type, user)
            tb.addItem(q, '{}:{}'.format(user_type, user))
        if before:
            row = tb.findData(before)
            if row > -1:
                tb.setCurrentIndex(row)
        tb.blockSignals(False)
        ub_is_visible = tb.count() > 2
        tb.setVisible(ub_is_visible), tb.la.setVisible(ub_is_visible)
        self.setVisible(tb_is_visible or ub_is_visible)


class BrowsePanel(QWidget):

    current_result_changed = pyqtSignal(object)
    open_annotation = pyqtSignal(object)

    def __init__(self, parent):
        QWidget.__init__(self, parent)
        self.use_stemmer = parent.use_stemmer
        self.current_query = None
        l = QVBoxLayout(self)

        h = QHBoxLayout()
        l.addLayout(h)
        self.search_box = sb = SearchBox(self)
        sb.initialize('library-annotations-browser-search-box')
        sb.cleared.connect(self.cleared)
        sb.lineEdit().returnPressed.connect(self.show_next)
        sb.lineEdit().setPlaceholderText(_('Enter words to search for'))
        h.addWidget(sb)

        self.next_button = nb = QToolButton(self)
        h.addWidget(nb)
        nb.setFocusPolicy(Qt.NoFocus)
        nb.setIcon(QIcon(I('arrow-down.png')))
        nb.clicked.connect(self.show_next)
        nb.setToolTip(_('Find next match'))

        self.prev_button = nb = QToolButton(self)
        h.addWidget(nb)
        nb.setFocusPolicy(Qt.NoFocus)
        nb.setIcon(QIcon(I('arrow-up.png')))
        nb.clicked.connect(self.show_previous)
        nb.setToolTip(_('Find previous match'))

        self.restrictions = rs = Restrictions(self)
        rs.restrictions_changed.connect(self.effective_query_changed)
        self.use_stemmer.stateChanged.connect(self.effective_query_changed)
        l.addWidget(rs)

        self.results_list = rl = ResultsList(self)
        rl.current_result_changed.connect(self.current_result_changed)
        rl.open_annotation.connect(self.open_annotation)
        l.addWidget(rl)

    def re_initialize(self):
        db = current_db()
        self.search_box.setFocus(Qt.OtherFocusReason)
        self.restrictions.re_initialize(db)

    def sizeHint(self):
        return QSize(450, 600)

    @property
    def effective_query(self):
        text = self.search_box.lineEdit().text().strip()
        if not text:
            return None
        atype = self.restrictions.types_box.currentData()
        if not atype or not atype.strip():
            atype = None
        user = self.restrictions.user_box.currentData()
        restrict_to_user = None
        if user and ':' in user:
            restrict_to_user = user.split(':', 1)
        return {
            'fts_engine_query': text,
            'annotation_type': atype,
            'restrict_to_user': restrict_to_user,
            'use_stemming': bool(self.use_stemmer.isChecked()),
        }

    def cleared(self):
        self.current_query = None
        self.results_list.clear()

    def do_find(self, backwards=False):
        q = self.effective_query
        if not q:
            return
        if q == self.current_query:
            self.results_list.show_next(backwards)
            return
        with BusyCursor():
            db = current_db()
            results = db.search_annotations(highlight_start='\x1d', highlight_end='\x1d', snippet_size=64, **q)
            self.results_list.set_results(results)
            self.current_query = q

    def effective_query_changed(self):
        self.do_find()

    def show_next(self):
        self.do_find()

    def show_previous(self):
        self.do_find(backwards=True)


class Details(QTextBrowser):

    def __init__(self, parent):
        QTextBrowser.__init__(self, parent)
        self.setFrameShape(self.NoFrame)
        self.setOpenLinks(False)
        self.setAttribute(Qt.WA_OpaquePaintEvent, False)
        palette = self.palette()
        palette.setBrush(QPalette.Base, Qt.transparent)
        self.setPalette(palette)
        self.setAcceptDrops(False)


class DetailsPanel(QWidget):

    open_annotation = pyqtSignal(object)

    def __init__(self, parent):
        QWidget.__init__(self, parent)
        self.current_result = None
        l = QVBoxLayout(self)
        self.text_browser = tb = Details(self)
        l.addWidget(tb)
        self.open_button = ob = QPushButton(QIcon(I('viewer.png')), _('Open in viewer'), self)
        ob.clicked.connect(self.open_result)
        l.addWidget(ob)
        self.show_result(None)

    def open_result(self):
        if self.current_result is not None:
            self.open_annotation.emit(self.current_result['annotation'])

    def sizeHint(self):
        return QSize(450, 600)

    def show_result(self, result_or_none):
        self.current_result = r = result_or_none
        if r is None:
            self.text_browser.setVisible(False)
            self.open_button.setVisible(False)
            return
        self.text_browser.setVisible(True)
        self.open_button.setVisible(True)
        db = current_db()
        book_id = r['book_id']
        title, authors = db.field_for('title', book_id), db.field_for('authors', book_id)
        authors = authors_to_string(authors)
        series, sidx = db.field_for('series', book_id), db.field_for('series_index', book_id)
        series_text = ''
        if series:
            use_roman_numbers = config['use_roman_numerals_for_series_number']
            series_text = '{0} of {1}'.format(fmt_sidx(sidx, use_roman=use_roman_numbers), series)
        annot = r['annotation']
        atype = annotation_title(annot['type'], singular=True)
        book_format = r['format']
        annot_text = ''
        a = prepare_string_for_xml

        for part in r['text'].split('\n\x1f\n'):
            segments = []
            for bit in part.split('\x1d'):
                segments.append(a(bit) + ('</b>' if len(segments) % 2 else '<b>'))
            stext = ''.join(segments)
            if stext.endswith('<b>'):
                stext = stext[:-3]
            annot_text += '<div style="text-align:left">' + stext + '</div><div>&nbsp;</div>'

        text = '''
        <h2 style="text-align: center">{title} [{book_format}]</h2>
        <div style="text-align: center">{authors}</div>
        <div style="text-align: center">{series}</div>
        <div>&nbsp;</div>
        <div>&nbsp;</div>
        <h2 style="text-align: left">{atype}</h2>
        {text}
        '''.format(
            title=a(title), authors=a(authors), series=a(series_text), book_format=a(book_format),
            atype=a(atype), text=annot_text
        )
        self.text_browser.setHtml(text)


class AnnotationsBrowser(Dialog):

    open_annotation = pyqtSignal(object)

    def __init__(self, parent=None):
        Dialog.__init__(self, _('Annotations browser'), 'library-annotations-browser-1', parent=parent)
        self.setAttribute(Qt.WA_DeleteOnClose, False)

    def do_open_annotation(self, annot):
        atype = annot['type']
        if atype == 'bookmark':
            if annot['pos_type'] == 'epubcfi':
                self.open_annotation.emit(annot['pos'])
        elif atype == 'highlight':
            x = 2 * (annot['spine_index'] + 1)
            self.open_annotation.emit('epubcfi(/{}{})'.format(x, annot['start_cfi']))

    def keyPressEvent(self, ev):
        if ev.key() not in (Qt.Key_Enter, Qt.Key_Return):
            return Dialog.keyPressEvent(self, ev)

    def setup_ui(self):
        self.use_stemmer = us = QCheckBox(_('Match on related English words'))
        us.setChecked(gprefs['browse_annots_use_stemmer'])
        us.setToolTip(fill(_(
            'With this option searching for words will also match on any related English words. For'
            ' example: correction matches correcting and corrected as well')))
        us.stateChanged.connect(lambda state: gprefs.set('browse_annots_use_stemmer', state != Qt.Unchecked))

        l = QVBoxLayout(self)

        self.splitter = s = QSplitter(self)
        l.addWidget(s)
        s.setChildrenCollapsible(False)

        self.browse_panel = bp = BrowsePanel(self)
        bp.open_annotation.connect(self.do_open_annotation)
        s.addWidget(bp)

        self.details_panel = dp = DetailsPanel(self)
        s.addWidget(dp)
        dp.open_annotation.connect(self.do_open_annotation)
        bp.current_result_changed.connect(dp.show_result)

        h = QHBoxLayout()
        l.addLayout(h)
        h.addWidget(us), h.addStretch(10), h.addWidget(self.bb)

    def show_dialog(self):
        self.browse_panel.re_initialize()
        if self.parent() is None:
            self.exec_()
        else:
            self.show()


if __name__ == '__main__':
    from calibre.library import db
    app = Application([])
    current_db.ans = db(os.path.expanduser('~/test library'))
    br = AnnotationsBrowser()
    br.show_dialog()
    del br
    del app
