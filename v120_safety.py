"""Safety gate for _seal_dead_code: valid Lua must never be altered.

Every case here is legal Lua. The repair is only allowed to leave them
byte-identical. A failure means the repair would delete live code.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mega_lua as M  # noqa: E402

CASES = {
    "multiline table return":
        'local t = {\n  a = 1,\n}\nreturn t\n',
    "multiline gsub return":
        'local function h(s)\n'
        '  return (s:gsub(".", function(c)\n'
        '    return c\n'
        '  end))\n'
        'end\n',
    "if/else both return":
        'function f(x)\n  if x then\n    return 1\n  else\n    return 2\n'
        '  end\nend\n',
    "return then elseif":
        'function g(x)\n  if x then\n    return 1\n  elseif x==2 then\n'
        '    return 2\n  else\n    return 3\n  end\nend\n',
    "RETURN CLOSURE (the killer)":
        'local r = r0()\n'
        'local function f()\n'
        '    return function(p1, p2)\n'
        '        local a = {}\n'
        '        local b = "text"\n'
        '        if type(p1)=="number" then\n'
        '            return a\n'
        '        end\n'
        '        return b\n'
        '    end\n'
        'end\n',
    "return closure inline end":
        'return function()\n  local x = 1\n  return x\nend\n',
    "repeat block":
        'local i=0\nrepeat\n  i=i+1\nuntil i>3\nreturn i\n',
    "return inside strings":
        'local s = "return"\nlocal t = [[\nreturn 5\n]]\nreturn s, t\n',
    "loop break last":
        'for i=1,10 do\n  if i>5 then\n    break\n  end\nend\nreturn true\n',
    "nested closure + return":
        'local function a()\n  return function()\n    return function()\n'
        '      return 42\n    end\n  end\nend\n',
    "do block return":
        'do\n  local x = 1\n  return x\nend\n',
    "return closure with args + body":
        'function m()\n  return function(self, cb)\n    local t = {}\n'
        '    for k,v in pairs(t) do cb(k,v) end\n    return t\n  end\nend\n',
    "method chain return":
        'function m()\n  local o = obj:build()\n  return o\nend\n',
    "goto forward to label":
        'for i=1,3 do\n  if i==2 then goto cont end\n  print(i)\n'
        '  ::cont::\nend\nreturn true\n',
    "goto loop back":
        'local i=0\n::top::\ni=i+1\nif i<3 then goto top end\nreturn i\n',
    "closure capturing after return":
        'local function f()\n  return function()\n    return function()\n'
        '      local z = 9\n      return z\n    end\n  end\nend\n',
    "return with method chain body":
        'local function build()\n  return {\n    run = function()\n'
        '      print("go")\n    end,\n  }\nend\n',
    # --- guards for the structural repairs (block closing, brackets, labels) ---
    "for/if/else all closed":
        'for i=1,10 do\n  if i%2==0 then\n    print(i)\n  else\n'
        '    print(-i)\n  end\nend\n',
    "repeat until closed":
        'repeat\n  local x=1\nuntil x==1\n',
    "while do belongs to loop":
        'while true do\n  break\nend\n',
    "nested function with if":
        'local function q()\n  if 1 then\n    return 2\n  end\nend\n',
    "else attached to a real if":
        'if a then\n  print(1)\nelse\n  print(2)\nend\n',
    "same label in two functions is legal":
        'local function a()\n  goto top\n  ::top::\n  return 1\nend\n'
        'local function b()\n  goto top\n  ::top::\n  return 2\nend\n',
    "balanced table across lines":
        'local t = {\n  a=1,\n  b={c=2},\n}\nreturn t\n',
    "long string properly closed":
        'local s = [==[ raw ]] text ]==]\nreturn s\n',
    "in as field and loop var":
        'for k, v in pairs({in=1}) do\n  print(k, v)\nend\n',
    "deep but complete nesting":
        "".join("if a then\n" for _ in range(30)) + "print(1)\n" + "end\n" * 30,
    "do block standalone":
        'do\n  local x=1\n  print(x)\nend\n',
    "if inside do inside for":
        'for i=1,3 do\n  do\n    if i then\n      print(i)\n    end\n  end\nend\n',
    "goto out of nested block":
        'do\n  do\n    goto out\n  end\nend\n::out::\nprint(1)\n',
}

bad = []
for name, src in CASES.items():
    out, notes = M._seal_dead_code(src)
    if out != src:
        bad.append(name)
        print(f"  [BAD] {name:34} MODIFIED {notes}")
    else:
        print(f"  [OK ] {name:34} untouched")

# Second gate: the WHOLE repair chain. A single repair in the fixpoint
# rewriting valid Lua is just as damaging as a bad dead-code seal, so every
# snippet above must also survive _apply_repairs() byte-identical.
print()
chain_bad = []
for name, src in CASES.items():
    out, notes = M._apply_repairs(src)
    if out != src or notes:
        chain_bad.append(name)
        print(f"  [BAD] {name:34} CHAIN MODIFIED {notes}")
    else:
        print(f"  [OK ] {name:34} chain clean")

print()
if bad or chain_bad:
    if bad:
        print(f"SAFETY: FAIL - _seal_dead_code altered {len(bad)}: {bad}")
    if chain_bad:
        print(f"SAFETY: FAIL - repair chain altered {len(chain_bad)}: {chain_bad}")
    sys.exit(1)
print(f"SAFETY: PASS - all {len(CASES)} valid snippets untouched by "
      f"_seal_dead_code and by the full repair chain")
