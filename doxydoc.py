import sublime, sublime_plugin
import re

def get_settings():
    return sublime.load_settings('Doxydoc.sublime-settings')


def get_setting(key, default=None):
    return get_settings().get(key, default)

setting = get_setting

def get_template_args(templates):
    print('Before: {0}'.format(templates))
    # Strip decltype statements
    templates = re.sub(r"decltype\(.+\)", "", templates)
    # Strip default parameters
    templates = re.sub(r"\s*=\s*.+,", ",", templates)
    # Strip type from template
    templates = re.sub(r"[A-Za-z_][\w.<>]*\s+([A-Za-z_][\w.<>]*)", r"\1", templates)
    print('After: {0}'.format(templates))
    return re.split(r",\s*", templates)

def read_line(view, point):
    if (point >= view.size()):
        return

    next_line = view.line(point)
    return view.substr(next_line)

def get_function_args(fn_str):
    print('Before: {0}'.format(fn_str))
    # Remove references and pointers
    fn_str = fn_str.replace("&", "")
    fn_str = fn_str.replace("*", "")

    # Remove va_list and variadic templates
    fn_str = fn_str.replace("...", "")

    # Remove cv-qualifiers
    fn_str = re.sub(r"(?:const|volatile)\s*", "", fn_str)

    # Remove namespaces
    fn_str = re.sub(r"\w+::", "", fn_str)

    # Remove template arguments in types
    fn_str = re.sub(r"([a-zA-Z_]\w*)\s*<.+>", r"\1", fn_str)

    # Remove parentheses
    fn_str = re.sub(r"\((.*)\)", r"\1", fn_str)

    # Remove arrays
    fn_str = re.sub(r"\[.*\]", "", fn_str)
    print('After: {0}'.format(fn_str))

    arg_regex = r"(?P<type>[a-zA-Z_]\w*)\s*(?P<name>[a-zA-Z_]\w*)"

    if ',' not in fn_str:
        if ' ' not in fn_str:
            return [("void", "")]
        else:
            m = re.search(arg_regex, fn_str)
            if m and m.group("type"):
                return [(m.group("type"), m.group("name"))]

    result = []
    for arg in fn_str.split(','):
        m = re.search(arg_regex, arg)
        if m and m.group('type'):
            result.append( (m.group('type'), m.group('name')) )

    return result

class DoxydocCommand(sublime_plugin.TextCommand):
    def set_up(self):
        identifier =  r"([a-zA-Z_]\w*)"
        function_identifiers = r"\s*(?:(?:inline|static|constexpr|friend|virtual|explicit|\[\[.+\]\])\s+)*"
        typedef_identifier = r"\s*(typedef)?\s*"
        cse_identifier = r"([a-zA-Z_]\w*)?"
        if get_setting("doxydoc_javadoc"):
            self.command_type = '@'
        else:
            self.command_type = '\\'
        self.regexp = {
            "templates": r"\s*template\s*<(.+)>\s*",
            "class": typedef_identifier + r"\s*class\s*" + cse_identifier + r"\s*{?",
            "struct": typedef_identifier + r"\s*struct\s*" + cse_identifier + r"\s*{?",
            "enum": typedef_identifier + r"\s*enum\s*" + cse_identifier + r"\s*{?",
            "define": r"\s*#\s*define\s*",
            "include": r"\s*#\s*include\s*",

            "function": function_identifiers + r"(?P<return>(?:typename\s*)?[\w:<>]+)?\s*"
                                               r"(?P<subname>[A-Za-z_]\w*::)?"
                                               r"(?P<name>operator\s*.{1,2}|[A-Za-z_:]\w*)\s*"
                                               r"\((?P<args>[:<>\[\]\(\),.*&\w\s=]*)\).+",

            "constructor": function_identifiers + r"(?P<return>)" # dummy so it doesn't error out
                                                  r"~?(?P<name>[a-zA-Z_]\w*)(?:\:\:[a-zA-Z_]\w*)?"
                                                  r"\((?P<args>[:<>\[\]\(\),.*&\w\s=]*)\).+",
        }

    def write(self, view, string):
        view.run_command("insert_snippet", {"contents": string })

    def run(self, edit, mode = None):
        if setting("doxydoc_enabled", True):
            self.set_up()
            snippet = self.retrieve_snippet(self.view)
            if snippet:
                self.write(self.view, snippet)
            else:
                sublime.status_message("DoxyDoc: Unable to retrieve snippet")

    def retrieve_snippet(self, view):
        point = view.sel()[0].begin()
        max_lines = setting("doxydoc_max_lines", 5)
        current_line = read_line(view, point)
        if not current_line or current_line.find("/**") == -1:
            # Strange bug..
            return "\n * ${0}\n */"
        point += len(current_line) + 1

        next_line = read_line(view, point)

        if not next_line:
            return "\n * ${0}\n */"

        # if the next line is already a comment, no need to reparse
        if re.search(r"^\s*\*", next_line):
            return "\n * "

        retempl = re.search(self.regexp["templates"], next_line)

        if retempl:
            # The following line is either a template function or
            # templated class/struct
            template_args = get_template_args(retempl.group(1))
            point += len(next_line) + 1
            second_line = read_line(view, point)
            function_line = read_line(view, point)
            function_point = point + len(function_line) + 1

            for x in range(0, max_lines + 1):
                line = read_line(view, function_point)

                if not line:
                    break
                function_line += line
                function_point += len(line) + 1

            # Check if it's a templated constructor or destructor
            reconstr = re.match(self.regexp["constructor"], function_line)

            if reconstr:
                return self.template_function_snippet(reconstr, template_args)

            # Check if it's a templated function
            refun = re.match(self.regexp["function"], function_line)

            if refun:
                return self.template_function_snippet(refun, template_args)

            # Check if it's a templated class
            reclass = re.match(self.regexp["class"], second_line)

            if reclass:
                return self.template_snippet(template_args)

        function_lines = ''.join(next_line) # make a copy
        function_point = point + len(next_line) + 1

        for x in range(0, max_lines + 1):
            line = read_line(view, function_point)

            if not line:
                break

            function_lines += line
            function_point += len(line) + 1

        # Check if it's the start of the file by checking
        # if we detect an include
        regex_start = re.search(self.regexp["include"], next_line)
        if regex_start:
            return self.start_snippet()

        # Check if it's a define
        regex_define = re.search(self.regexp["define"], next_line)
        if regex_define:
            return self.define_snippet()

        # Check if it's a regular class
        regex_class = re.search(self.regexp["class"], next_line)
        if regex_class:
            return self.class_snippet()

        # Check if it's a regular struct
        regex_struct = re.search(self.regexp["struct"], next_line)
        if regex_struct:
            return self.struct_snippet()

        # Check if it's a regular struct
        regex_enum = re.search(self.regexp["enum"], next_line)
        if regex_enum:
            return self.enum_snippet()

        # Check if it's a regular constructor or destructor
        regex_constructor = re.match(self.regexp["constructor"], function_lines)
        if regex_constructor:
            return self.function_snippet(regex_constructor)

        # Check if it's a regular function
        regex_function = re.search(self.regexp["function"], function_lines)
        if regex_function:
            return self.function_snippet(regex_function)

        # if all else fails, just send a closing snippet
        return "\n * ${0}\n */"


    def regular_snippet(self):
        snippet = ("\n * {0}brief ${{1:[brief description]}}"
                   "\n * {0}details ${{2:[long description]}}\n * \n */".format(self.command_type))
        return snippet

    def class_snippet(self):
        snippet = ("\n * {0}class ${{1:[class name]}}"
                   "\n * {0}brief ${{2:[brief description]}}"
                   "\n * {0}details ${{3:[long description]}}\n */".format(self.command_type))
        return snippet

    def struct_snippet(self):
        snippet = ("\n * {0}struct ${{1:[struct name]}}"
                   "\n * {0}brief ${{2:[brief description]}}"
                   "\n * {0}details ${{3:[long description]}}\n */".format(self.command_type))
        return snippet

    def enum_snippet(self):
        snippet = ("\n * {0}enum ${{1:[enum name]}}"
                   "\n * {0}brief ${{2:[brief description]}}"
                   "\n * {0}details ${{3:[long description]}}\n */".format(self.command_type))
        return snippet

    def start_snippet(self):
        snippet = ("\n * {0}file ${{1:[file name]}}"
                   "\n * {0}brief ${{2:[brief description]}}"
                   "\n * {0}details ${{3:[long description]}}\n *"
                   "\n * {0}author ${{4:[authors name]}}"
                   "\n * {0}date ${{5:[file date]}}"
                   "\n * {0}copyright ${{6:[copyright description]}}\n */".format(self.command_type))
        return snippet

    def define_snippet(self):
        snippet = ("\n * {0}def ${{1:[macro name]}}"
                   "\n * {0}brief ${{2:[brief description]}}"
                   "\n * {0}details ${{3:[long description]}}\n * \n */".format(self.command_type))
        return snippet

    def template_snippet(self, template_args):
        snippet = ("\n * {0}brief ${{1:[brief description]}}"
                   "\n * {0}details ${{2:[long description]}}\n * ".format(self.command_type))

        index = 3
        for x in template_args:
            snippet += "\n * {0}tparam {1} ${{{2}:[description]}}".format(self.command_type, x, index)
            index += 1

        snippet += "\n */"
        return snippet

    def template_function_snippet(self, regex_obj, template_args):
        snippet = ""
        index = 1
        snippet =  ("\n * {0}brief ${{{1}:[brief description]}}"
                    "\n * {0}details ${{{2}:[long description]}}\n * ".format(self.command_type, index, index + 1))
        index += 2

        # Function arguments
        args = regex_obj.group("args")

        if args and args.lower() != "void":
            args = get_function_args(args)
            for type, name in args:
                if type in template_args:
                    template_args.remove(type)
                snippet += "\n * {0}param {1} ${{{2}:[description]}}".format(self.command_type, name, index)
                index += 1

        for arg in template_args:
            snippet += "\n * {0}tparam {1} ${{{2}:[description]}}".format(self.command_type, arg, index)
            index += 1

        return_type = regex_obj.group("return")

        if return_type and return_type != "void":
            snippet += "\n * {0}return ${{{1}:[description]}}".format(self.command_type, index)

        snippet += "\n */"
        return snippet

    def function_snippet(self, regex_obj):
        fn = regex_obj.group(0)
        index = 1
        snippet =  ("\n * {0}brief ${{{1}:[brief description]}}"
                    "\n * {0}details ${{{2}:[long description]}}".format(self.command_type, index, index + 1))
        index += 2

        args = regex_obj.group("args")

        if args and args.lower() != "void":
            snippet += "\n * "
            args = get_function_args(args)
            for _, name in args:
                snippet += "\n * {0}param {1} ${{{2}:[description]}}".format(self.command_type, name, index)
                index += 1

        return_type = regex_obj.group("return")

        if return_type and return_type != "void":
            if index == 5:
                snippet += "\n * "
            snippet += "\n * {0}return ${{{1}:[description]}}".format(self.command_type, index)

        snippet += "\n */"
        return snippet

class DoxygenCompletions(sublime_plugin.EventListener):
    def __init__(self):
        self.command_type = '@' if setting('doxydoc_javadoc', True) else '\\'

    def default_completion_list(self):
        return [('author',        'author ${1:[author]}'),
                ('date',          'exception ${1:[date]}'),
                ('deprecated',    'deprecated ${1:[deprecated-text]}'),
                ('exception',     'exception ${1:[exception-object]} ${2:[description]}'),
                ('param',         'param ${1:[parameter-name]} ${2:[description]}'),
                ('return',        'return ${1:[description]}'),
                ('see',           'see ${1:[reference]}'),
                ('since',         'since ${1:[since-text]}'),
                ('throws',        'throws ${1:[exception-object]} ${2:[description]}'),
                ('version',       'version ${1:[version-text]}'),
                ('code',          'code \n* ${0:[text]}\n* @endcode'),
                ('bug',           'bug ${1:[bug-text]}'),
                ('details',       'details ${1:[detailed-text]}'),
                ('warning',       'warning ${1:[warning-message]}'),
                ('todo',          'todo ${1:[todo-text]}'),
                ('defgroup',      'defgroup ${1:[group-name]} ${2:[group-title]}'),
                ('ingroup',       'ingroup ${1:[group-name]...}'),
                ('addtogroup',    'addtogroup ${1:[group-name]} ${2:[group-title]}'),
                ('weakgroup',     'weakgroup ${1:[group-name]} ${2:[group-title]}')]

    def on_query_completions(self, view, prefix, locations):
        # Only trigger within comments
        if not view.match_selector(locations[0], 'comment'):
            return []

        pt = locations[0] - len(prefix) - 1
        # Get character before
        ch = view.substr(sublime.Region(pt, pt + 1))

        flags = sublime.INHIBIT_WORD_COMPLETIONS | sublime.INHIBIT_EXPLICIT_COMPLETIONS

        # Character given isn't \ or @
        if ch != self.command_type:
            return ([], flags)

        return (self.default_completion_list(), flags)
