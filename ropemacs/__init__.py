import rope.refactor.extract
import rope.refactor.inline
import rope.refactor.move
from Pymacs import lisp
from rope.base import project, libutils
from rope.contrib import codeassist, generate

from ropemacs import refactor


def interactive(func):
    func.interaction = ''
    return func

def lispfunction(func):
    func.lisp = None
    return func


class RopeInterface(object):

    def __init__(self):
        self.project = None
        self.old_content = None

    @lispfunction
    def init(self):
        """Initialize rope mode"""
        lisp.add_hook(lisp.before_save_hook, lisp.rope_before_save_actions)
        lisp.add_hook(lisp.after_save_hook, lisp.rope_after_save_actions)
        lisp.add_hook(lisp.kill_emacs_hook, lisp.rope_exiting_actions)
        lisp.add_hook(lisp.python_mode_hook, lisp.rope_register_local_keys)

        lisp(DEFVARS)

        self.global_keys = [
            ('C-x p o', lisp.rope_open_project),
            ('C-x p k', lisp.rope_close_project),
            ('C-x p u', lisp.rope_undo_refactoring),
            ('C-x p r', lisp.rope_redo_refactoring),
            ('C-x p f', lisp.rope_find_file)]

        self.local_keys = [
            ('C-c r r', lisp.rope_rename),
            ('C-c r l', lisp.rope_extract_variable),
            ('C-c r m', lisp.rope_extract_method),
            ('C-c r i', lisp.rope_inline),
            ('C-c r v', lisp.rope_move),
            ('C-c r x', lisp.rope_restructure),
            ('C-c r 1 r', lisp.rope_rename_current_module),
            ('C-c r 1 v', lisp.rope_move_current_module),
            ('C-c r 1 p', lisp.rope_module_to_package),

            ('M-/', lisp.rope_code_assist),
            ('C-c g', lisp.rope_goto_definition),
            ('C-c C-d', lisp.rope_show_doc),
            ('C-c i o', lisp.rope_organize_imports),

            ('C-c n v', lisp.rope_generate_variable),
            ('C-c n f', lisp.rope_generate_function),
            ('C-c n c', lisp.rope_generate_class),
            ('C-c n m', lisp.rope_generate_module),
            ('C-c n p', lisp.rope_generate_package)]

        for key, callback in self.global_keys:
            lisp.global_set_key(self._key_sequence(key), callback)

    def _key_sequence(self, sequence):
        result = []
        for key in sequence.split():
            if key.startswith('C-'):
                number = ord(key[-1].upper()) - ord('A') + 1
                result.append(chr(number))
            elif key.startswith('M-'):
                number = ord(key[-1].upper()) + 0x80
                result.append(chr(number))
            else:
                result.append(key)
        return ''.join(result)

    @lispfunction
    def before_save_actions(self):
        if self.project is not None:
            resource = self._get_resource()
            if resource is not None and resource.exists():
                self.old_content = resource.read()
            else:
                self.old_content = ''

    @lispfunction
    def after_save_actions(self):
        if self.project is not None:
            libutils.report_change(self.project, lisp.buffer_file_name(),
                                   self.old_content)
            self.old_content = None

    @lispfunction
    def register_local_keys(self):
        for key, callback in self.local_keys:
            lisp.local_set_key(self._key_sequence(key), callback)

    @lispfunction
    def exiting_actions(self):
        if self.project is not None:
            self.close_project()

    @interactive
    def open_project(self):
        root = lisp.read_directory_name('Rope project root folder: ')
        if self.project is not None:
            self.close_project()
        self.project = project.Project(root)

    @interactive
    def close_project(self):
        if project is not None:
            self.project.close()
            self.project = None
            lisp.message('Project closed')

    @interactive
    def undo_refactoring(self):
        if lisp.y_or_n_p('Undo refactoring might change'
                         ' many files; proceed? '):
            self._check_project()
            for changes in self.project.history.undo():
                self._reload_buffers(changes.get_changed_resources())

    @interactive
    def redo_refactoring(self):
        if lisp.y_or_n_p('Redo refactoring might change'
                         ' many files; proceed? '):
            self._check_project()
            for changes in self.project.history.redo():
                self._reload_buffers(changes.get_changed_resources())

    @interactive
    def rename(self):
        refactor.Rename(self).show()

    @interactive
    def rename_current_module(self):
        refactor.RenameCurrentModule(self).show()

    @interactive
    def move(self):
        refactor.Move(self).show()

    @interactive
    def move_current_module(self):
        refactor.MoveCurrentModule(self).show()

    @interactive
    def module_to_package(self):
        self._check_project()
        self._save_buffers(only_current=True)
        packager = rope.refactor.ModuleToPackage(self.project,
                                                 self._get_resource())
        self._perform(packager.get_changes())

    def _do_extract(self, extractor, prompt):
        self._check_project()
        self._save_buffers(only_current=True)
        resource = self._get_resource()
        start, end = self._get_region()
        extractor = extractor(self.project, resource, start, end)
        newname = _ask(prompt)
        changes = extractor.get_changes(newname)
        self._perform(changes)

    @interactive
    def extract_variable(self):
        self._do_extract(rope.refactor.extract.ExtractVariable,
                         'New Variable Name: ')

    @interactive
    def extract_method(self):
        self._do_extract(rope.refactor.extract.ExtractMethod,
                         'New Method Name: ')

    @interactive
    def inline(self):
        self._check_project()
        self._save_buffers()
        resource, offset = self._get_location()
        inliner = rope.refactor.inline.create_inline(
            self.project, resource, offset)
        self._perform(inliner.get_changes())

    @interactive
    def restructure(self):
        restruturing = refactor.Restructure(self)
        return restruturing.show()

    @interactive
    def organize_imports(self):
        self._check_project()
        self._save_buffers(only_current=True)
        organizer = rope.refactor.ImportOrganizer(self.project)
        self._perform(organizer.organize_imports(self._get_resource()))

    def _perform(self, changes):
        if changes is None:
            return
        self.project.do(changes)
        self._reload_buffers(changes.get_changed_resources())
        lisp.message(str(changes.description) + ' finished')

    def _get_region(self):
        offset1 = self._get_offset()
        lisp.exchange_point_and_mark()
        offset2 = self._get_offset()
        lisp.exchange_point_and_mark()
        return min(offset1, offset2), max(offset1, offset2)

    def _get_offset(self):
        return lisp.point() - 1

    @interactive
    def goto_definition(self):
        self._check_project()
        resource, offset = self._get_location()
        definition = codeassist.get_definition_location(
            self.project, lisp.buffer_string(), offset, resource)
        self._goto_location(definition)

    @interactive
    def show_doc(self):
        self._check_project()
        resource, offset = self._get_location()
        docs = codeassist.get_doc(
            self.project, lisp.buffer_string(), offset, resource)
        pydoc_buffer = lisp.get_buffer_create('*rope-pydoc*')
        lisp.set_buffer(pydoc_buffer)
        lisp.erase_buffer()
        if docs:
            lisp.insert(docs)
            lisp.display_buffer(pydoc_buffer)

    @interactive
    def code_assist(self):
        self._check_project()
        resource, offset = self._get_location()
        source = lisp.buffer_string()
        proposals = codeassist.code_assist(self.project, source,
                                           offset, resource)
        proposals = codeassist.sorted_proposals(proposals)
        starting_offset = codeassist.starting_offset(source, offset)
        names = [proposal.name for proposal in proposals]
        starting = source[starting_offset:offset]
        prompt = 'Completion for %s: ' % starting
        result = _ask_values(prompt, names, starting=starting, exact=False)
        lisp.delete_region(starting_offset + 1, offset + 1)
        lisp.insert(result)

    @interactive
    def find_file(self):
        self._check_project()
        files = self.project.get_files()
        names = []
        for file in files:
            names.append('<'.join(reversed(file.path.split('/'))))
        source = lisp.buffer_string()
        result = _ask_values('Rope Find File: ', names, exact=True)
        path = '/'.join(reversed(result.split('<')))
        file = self.project.get_file(path)
        lisp.find_file(file.real_path)

    def _generate_element(self, kind):
        self._check_project()
        self._save_buffers()
        resource, offset = self._get_location()
        generator = generate.create_generate(kind, self.project,
                                             resource, offset)
        self._perform(generator.get_changes())
        self._goto_location(generator.get_location())

    def _goto_location(self, location, readonly=False):
        if location[0]:
            resource = location[0]
            if resource.project == self.project:
                lisp.find_file(str(location[0].real_path))
            else:
                lisp.find_file_read_only(str(location[0].real_path))
        if location[1]:
            lisp.goto_line(location[1])

    @interactive
    def generate_variable(self):
        self._generate_element('variable')

    @interactive
    def generate_function(self):
        self._generate_element('function')

    @interactive
    def generate_class(self):
        self._generate_element('class')

    @interactive
    def generate_module(self):
        self._generate_element('module')

    @interactive
    def generate_package(self):
        self._generate_element('package')

    def _get_location(self):
        resource = self._get_resource()
        offset = self._get_offset()
        return resource, offset

    def _get_resource(self, filename=None):
        if filename is None:
            filename = lisp.buffer_file_name()
        resource = libutils.path_to_resource(self.project, filename, 'file')
        return resource

    def _check_project(self):
        if self.project is None:
            lisp.call_interactively(lisp.rope_open_project)
        else:
            self.project.validate(self.project.root)

    def _reload_buffers(self, changed_resources):
        for resource in changed_resources:
            buffer = lisp.find_buffer_visiting(str(resource.real_path))
            if buffer and resource.exists():
                lisp.set_buffer(buffer)
                lisp.revert_buffer(None, 1)

    def _save_buffers(self, only_current=False):
        ask = lisp['rope-confirm-saving'].value()
        initial = lisp.current_buffer()
        current_buffer = lisp.current_buffer()
        if only_current:
            buffers = [current_buffer]
        else:
            buffers = lisp.buffer_list()
        for buffer in buffers:
            filename = lisp.buffer_file_name(buffer)
            if filename:
                if self._is_a_project_python_file(filename) and \
                   lisp.buffer_modified_p(buffer):
                    if not ask or lisp.y_or_n_p('Save %s buffer?' % filename):
                        lisp.set_buffer(buffer)
                        lisp.save_buffer()
        lisp.set_buffer(initial)

    def _is_a_project_python_file(self, path):
        resource = self._get_resource(path)
        return (resource is not None and resource.exists() and
                resource.project == self.project and
                self.project.pycore.is_python_file(resource))


def _register_functions(interface):
    for attrname in dir(interface):
        attr = getattr(interface, attrname)
        if hasattr(attr, 'interaction') or hasattr(attr, 'lisp'):
            globals()[attrname] = attr


def _ask(prompt, default=None, starting=None):
    if default is not None:
        prompt = prompt + ('[%s] ' % default)
    result =  lisp.read_from_minibuffer(prompt, starting, None, None,
                                        None, default, None)
    if result == '' and default is not None:
        return default
    return result

def _ask_values(prompt, values, default=None, starting=None, exact=True):
    if exact and default is not None:
        prompt = prompt + ('[%s] ' % default)
    result = lisp.completing_read(prompt, values, None, exact, starting)
    if result == '' and exact:
        return default
    return result

def _lisp_askdata(data):
    if data.values:
        return _ask_values(data.prompt, data.values, default=data.default,
                           starting=data.starting)
    else:
        return _ask(data.prompt, default=data.default, starting=data.starting)


DEFVARS = """\
(defvar rope-confirm-saving t
  "If non-nil, you have to confirm saving all modified
python files before refactorings; otherwise they are
saved automatically.")
"""

interface = RopeInterface()
_register_functions(interface)
