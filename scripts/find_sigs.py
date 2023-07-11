#!/usr/bin/env python3
import binaryninja
from glob import glob
import re
from multiprocessing import Pool, cpu_count, set_start_method
import sigkit.sigkit


# this doesn't handle types correctly, but it works
# for what i need it to so problem for later.
def hlil_to_expression(hlil_instruction):
    if isinstance(hlil_instruction, binaryninja.HighLevelILInstruction):
        operands = []
        for operand in hlil_instruction.operands:
            if isinstance(operand, list):
                operands.append(
                    "("
                    + ", ".join(hlil_to_expression(inner) for inner in operand)
                    + ")"
                )
            else:
                operands.append(hlil_to_expression(operand))
        expr = "{}({})".format(hlil_instruction.operation.name, ", ".join(operands))
    else:
        expr = str(hlil_instruction)
    return expr


# ?? => capture wildcard
# .. => non-captured wildcard
# (supports multiline expressions)
def expression_extract_wildcard(hlil, expressions):
    for expression in expressions:
        pattern = expression.replace("(", "\\(").replace(")", "\\)")
        pattern = pattern.replace("..", "\\w+").replace("??", "(\\w+)")
        match = re.search(pattern, hlil)
        if match:
            return (expression, match.group(1))
    return (None, None)


expressions = {
    "CL_GetDownloadQueueSize": (
        "HLIL_IF(HLIL_CMP_E(HLIL_CALL(HLIL_CONST_PTR(??), ()), HLIL_CONST(0)))",
    ),  # universal
    "CL_DownloadUpdate": (
        "HLIL_IF(HLIL_AND(HLIL_CMP_NE(HLIL_VAR(..), HLIL_CONST(0)), HLIL_CMP_E(HLIL_CALL(HLIL_CONST_PTR(??), ()), HLIL_CONST(0)))",  # linux
        "HLIL_ASSIGN(HLIL_VAR(..), HLIL_CALL(HLIL_CONST_PTR(??), ()))",  # windows
    ),
    "CL_QueueDownload": (
        "HLIL_CALL(HLIL_CONST_PTR(??), (HLIL_VAR(..), HLIL_VAR(..)))",  # linux & windows x64
        "HLIL_CALL(HLIL_CONST_PTR(??), (HLIL_VAR(..), HLIL_VAR(..), HLIL_VAR(..), HLIL_VAR(..), HLIL_VAR(..)))",  # windows x86
    ),
}


def spawn(binary):
    binaryninja.set_worker_thread_count(1)
    with binaryninja.open_view(binary) as bv:
        text = next(bv.find_all_text(bv.start, bv.end, "CheckUpdatingSteamResources"))
        func = bv.get_functions_containing(text[0])[0]

        instructions = func.hlil.instructions
        hlil = "\n".join([hlil_to_expression(instr) for instr in instructions])

        # print(hlil)

        values = [
            (name, expression_extract_wildcard(hlil, expr))
            for name, expr in expressions.items()
        ]
        values = [
            (name, (pattern, int(val)))
            for name, (pattern, val) in values
            if val is not None
        ]

        for name, (pattern, addr) in values:
            print("\n~ %s:%s => 0x%x" % (binary, name, addr))
            func = bv.get_function_at(addr)
            node, info = sigkit.generate_function_signature(func, False)
            pattern = info.patterns[0]

            # skidscan supposedly supports not having spaces in sig
            # it doesn't.
            pattern = " ".join(map(str, pattern._array))
            print("~ sig: %s" % pattern)


if __name__ == "__main__":
    print(
        "~ NOTE: this script takes a while to run due to binaryninja's analysis process."
    )
    set_start_method("spawn")
    processes = cpu_count() - 1 if cpu_count() > 1 else 1
    pool = Pool(processes=processes)
    results = []
    for binary in glob("./bin/*"):
        results.append(pool.apply_async(spawn, (binary,)))

    for result in results:
        result.get()
    pool.close()
