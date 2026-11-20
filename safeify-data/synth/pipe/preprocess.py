"""Pipeline-identical port of SafeNet's AST preprocessing.

Ports (verbatim transformation logic, paths parameterized):
  vendors/SafeNet/src/process/rust_asttree-json/simplifyast.py   -> simplify_ast()
  vendors/SafeNet/src/process/rust_asttree-json/addnumtree.py    -> preorder_from_simplified()

Input : `.ast` files produced by syn's `{:#?}` Debug dump (extract_ast tool).
Output: the preorder token sequence with branch counts, JSON-serialized exactly
        the way addnumtree.py writes it (a JSON string), i.e. the `text1`/`text2`
        cells of SafeNet's train.csv.

Known deviation from the committed script (documented in research/synth/README.md):
the committed simplifyast.py renames *every* ident to varN, yet the shipped
train.csv contains literal known idents (`mem`, `transmute`, `NonNull`, `Arc`...).
The shipped data therefore must have been produced with the ident filter that
exists in the sibling script astsimpletree.py (`if ident not in res_dict`).
We keep that filter so synthetic rows are distribution-compatible with the
baseline data. The str.replace prefix-collision behaviour of the original
(e.g. var7llocator in train.csv) is preserved on purpose.
"""

import json
import os
import re


def get_res_dict():
    """Known-ident table copied from simplifyast.py (keys are case-sensitive)."""
    return {
        "unsafe": None, "Box": None, "MaybeUninit": None, "Rc": None, "Arc": None,
        "Vec": None, "slice": None, "str": None, "map": None, "HashMap": None,
        "vec!": None, "alloc": None, "String": None, "array": None, "struct": None,
        "UnsafeCell": None, "Option": None, "Result": None, "Some": None,
        "NonZero": None, "NonNull": None, "Pin": None, "Layout": None, "mut": None,
        "const": None, "as": None, "array_assume_init": None, "as_bytes_mut": None,
        "as_chunks_unchecked": None, "as_chunks_unchecked_mut": None, "as_ptr": None,
        "as_mut_ptr": None, "as_ref": None, "as_uninit_ref": None, "assume_init": None,
        "as_mut": None, "cell": None, "dealloc": None, "clone": None,
        "deallocate": None, "drop": None, "drop_in_place": None,
        "downcast_unchecked": None, "expect": None, "forget": None, "free": None,
        "from": None, "from_le_bytes": None, "from_raw": None, "from_raw_in": None,
        "from_raw_parts": None, "from_raw_parts_mut": None, "get": None,
        "get_mut_unchecked": None, "get_unchecked": None, "get_unchecked_mut": None,
        "into": None, "into_raw": None, "into_raw_with_allocator": None, "len": None,
        "libc": None, "malloc": None, "new_unchecked": None, "new_uninit": None,
        "new_uninit_slice": None, "new": None, "new_in": None, "new_zeroed": None,
        "new_zeroed_slice": None, "offset": None, "offset_from": None, "set_len": None,
        "swap_unchecked": None, "split_at_unchecked": None,
        "split_at_mut_unchecked": None, "slice_unchecked": None, "sub": None,
        "transmute": None, "to_int_unchecked": None, "to_owned": None, "uninit": None,
        "uninit_array": None, "unwrap_unchecked": None, "unwrap_err_unchecked": None,
        "unchecked_mul": None, "unchecked_add": None, "wrap": None,
        "wrapping_offset": None, "wrapping_add": None, "wrapping_sub": None,
        "write": None, "zeroed": None, "main": None, "mem": None, "key": None,
        "ptr": None, "self": None, "num": None,
    }


def simplify_bracket(src):
    """Copied verbatim from astsimpletree.py/simplifyast.py."""
    stack = []
    splited = re.split(r"([\(\)])", src)
    for p in [e for e in splited if e]:
        if p != ")":
            stack.append(p)
        else:
            temp = ""
            for i, _ in enumerate(range(len(stack))):
                s_pop = stack.pop(-1)
                if s_pop == "(":
                    if i <= 1:
                        if "(" not in temp:
                            stack.append(f"({temp})")
                        else:
                            stack.append(temp)
                    else:
                        stack.append(f"({temp})")
                    break
                else:
                    temp = s_pop + temp
    return "".join(stack)


def simplify_ast(debug_string):
    """Port of the simplifyast.py body: syn Debug dump -> simplified bracket string."""
    res_dict = get_res_dict()
    string = debug_string
    string = re.sub('ident:[ \\w]{1,}\\([\\n ]*([\\w]{1,},)[\\n ]*\\),', 'ident: \\g<1>', string, flags=re.S)
    string = re.sub('method:[ \\w]{1,}\\([\\n ]*([\\w]{1,},)[\\n ]*\\),', 'ident: \\g<1>', string, flags=re.S)
    string = string.replace('\n', '').replace(' ', '')
    string = string.replace("{", "(").replace("}", ")").replace("[", "(").replace("]", ")")
    string = string.replace('(eq,', '( eq,').replace('(Mut,', '( Mut,').replace('(Dot2,', '( Dot2,').replace('(Colon2,', '( Colon2,')

    result = re.findall(r'([()])|(ident:\w*)|(\w*token\w*:([^N]\w*))|( eq,)|( Mut,)|( Colon2,)', string, flags=re.I)
    result = [''.join(i).strip().strip(',') for i in result]
    result = [i if i in '()' else f'({i})' for i in result]
    output = ''.join(result)

    result = re.findall(r'\((ident:\w{1,})\)', output)
    filter_res = [i.split(':') for i in result]

    # ident filter kept from the data (see module docstring): known idents stay literal
    di = {}
    for i in filter_res:
        if i[-1] in res_dict:
            continue
        if i[-1] not in di:
            di[i[-1]] = f'var{len(di) + 1}'

    for k in di:
        output = output.replace('ident:' + k, 'ident:' + di[k])

    token_find = re.findall(r'(([^()]*token[^()]*):([^()]+))', output)
    for t, p, s in token_find:
        output = output.replace(t, p)
    ident_find = re.findall(r'(([^()]*ident[^()]*):([^()]+))', output)
    for t, p, s in ident_find:
        output = output.replace(t, s)

    output = output.replace("()", "")
    return simplify_bracket(output)


class TreeNode:
    def __init__(self, value):
        self.value = value
        self.children = []

    def add_child(self, child):
        self.children.append(child)

    def preorder_traversal(self):
        result = [self.value]
        for child in self.children:
            result.extend(child.preorder_traversal())
        return result


def complete_tree(node):
    """Copied verbatim from addnumtree.py (branch-count encoding)."""
    if not node.children:
        return
    for i in range(len(node.children)):
        child = node.children[i]
        if child.value == '()':
            child.add_child(TreeNode('0'))
        complete_tree(child)
        node.value = f"{len(node.children)}"
    node.children = [child for child in node.children if child.value != '()']


def preorder_from_simplified(simplified_str):
    """Port of addnumtree.process_file: simplified bracket string -> preorder seq."""
    node_str = simplified_str.strip().replace('()', '')

    tree = TreeNode('')
    stack = [tree]
    current_node = tree
    i = 0
    while i < len(node_str):
        if node_str[i] == '(':
            new_node = TreeNode('')
            current_node.add_child(new_node)
            stack.append(new_node)
            current_node = new_node
        elif node_str[i] == ')':
            stack.pop()
            current_node = stack[-1]
        else:
            start = i
            while i < len(node_str) and node_str[i] != '(' and node_str[i] != ')':
                i += 1
            value = node_str[start:i]
            current_node.value = value
            i -= 1
        i += 1

    complete_tree(tree)
    preorder_sequence = ' '.join(tree.preorder_traversal()[1:])
    if preorder_sequence:
        numbers = preorder_sequence.split()
        if numbers[0].isdigit():
            numbers[0] = str(int(numbers[0]) - 1)
            preorder_sequence = ' '.join(numbers)
    return preorder_sequence


def ast_file_to_preorder(ast_path):
    with open(ast_path, 'r', encoding='utf-8') as f:
        debug_dump = f.read()
    simplified = simplify_ast(debug_dump)
    return preorder_from_simplified(simplified)


def ast_file_to_json(ast_path, out_json_path):
    """Mirror of addnumtree.py's writer: JSON string of the preorder seq."""
    seq = ast_file_to_preorder(ast_path)
    out_dir = os.path.dirname(out_json_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(out_json_path, 'w', encoding='utf-8') as f:
        json.dump(seq, f)
    return seq

