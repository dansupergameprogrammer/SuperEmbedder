"""TE-114: nonempty root source properties compile identically in both libraries.

The mismatch control changes a target compile definition after creation; the
existing real-command comparator must reject it. Source properties themselves
share root scope, so independently diverging their values is structurally gone.
"""
from pathlib import Path
import json
from support.workspace_build_control import ROOT, parser, build, save
from u1_raw_text_cells_check import Table, workspace_interface


def main():
    args = parser(__doc__).parse_args()
    root = Path(args.build_dir).resolve(); root.mkdir(parents=True,exist_ok=True)
    records=[]; outcomes=[]
    try:
        for mismatch in (False,True):
            name='mismatch' if mismatch else 'healthy'
            work=root/name; work.mkdir(parents=True,exist_ok=True)
            inc=work/'build/property-inputs/include'; inc.mkdir(parents=True,exist_ok=True)
            header=inc/'k15_source_property_probe.h'
            header.write_text('''#if !defined(SEMB_SOURCE_DEFINITION) || !defined(SEMB_SOURCE_OPTION) || !defined(SEMB_SOURCE_CONFIG) || !defined(SEMB_SOURCE_FLAG)
#error nonempty source property was dropped
#endif
''',encoding='utf-8')
            dependency=work/'build/property-inputs/object-dependency.txt'; dependency.write_text('K-15 explicit source object dependency\n')
            project=work/'project.cmake'
            # cl and clang-cl share the MSVC frontend; GNU drivers use -include.
            msvc=Path(args.cxx_compiler).name.lower() in ('cl','cl.exe','clang-cl','clang-cl.exe')
            option='/DSEMB_SOURCE_OPTION=1' if msvc else '-DSEMB_SOURCE_OPTION=1'
            flags='/DSEMB_SOURCE_FLAG=1' if msvc else '-DSEMB_SOURCE_FLAG=1'
            forced='/FIk15_source_property_probe.h' if msvc else '-include;k15_source_property_probe.h'
            project.write_text(f'''set_source_files_properties("${{CMAKE_SOURCE_DIR}}/src/version.cpp" PROPERTIES
  COMPILE_DEFINITIONS "SEMB_SOURCE_DEFINITION=1;$<$<CONFIG:Release>:SEMB_SOURCE_CONFIG=1>"
  COMPILE_OPTIONS "{option};{forced}"
  COMPILE_FLAGS "{flags}"
  INCLUDE_DIRECTORIES "{inc.as_posix()}"
  OBJECT_DEPENDS "{dependency.as_posix()}"
  SEMB_CUSTOM_SOURCE_PROPERTY "custom-source-scope-probe")
function(semb_property_control_late)
  get_target_property(_prod_dir superembedder SOURCE_DIR)
  get_target_property(_seam_dir superembedder_testseam SOURCE_DIR)
  if(NOT _prod_dir STREQUAL _seam_dir)
    message(FATAL_ERROR "K-15 source property scopes differ")
  endif()
  get_source_file_property(_custom "${{CMAKE_SOURCE_DIR}}/src/version.cpp" TARGET_DIRECTORY superembedder_testseam SEMB_CUSTOM_SOURCE_PROPERTY)
  if(NOT _custom STREQUAL "custom-source-scope-probe")
    message(FATAL_ERROR "K-15 custom source property was dropped")
  endif()
  {'target_compile_definitions(superembedder_testseam PRIVATE SEMB_SOURCE_MISMATCH=1)' if mismatch else ''}
endfunction()
function(semb_property_control_queue)
  cmake_language(DEFER CALL semb_property_control_late)
endfunction()
cmake_language(DEFER CALL semb_property_control_queue)
''',encoding='utf-8')
            build(args,work/'build',['-DCMAKE_PROJECT_superembedder_INCLUDE='+project.as_posix()],records)
            table=Table(); matched=workspace_interface(work/'build',table)
            compile_rows=json.loads((work/'build/compile_commands.json').read_text())
            version=[r for r in compile_rows if Path(r['file']).name=='version.cpp']
            if len(version)!=2 or any(not all(marker in r['command'].replace('\\','/') for marker in
                    ('SEMB_SOURCE_DEFINITION=1','SEMB_SOURCE_OPTION=1','SEMB_SOURCE_CONFIG=1','SEMB_SOURCE_FLAG=1',
                     'k15_source_property_probe.h',inc.as_posix())) for r in version):
                raise RuntimeError('nonempty real compile-property population absent')
            # OBJECT_DEPENDS is a build dependency, not a compiler argument.
            # Check both actual Ninja object edges carry the same dependency.
            edges=[line for line in (work/'build/build.ninja').read_text().splitlines()
                   if line.startswith('build ') and ('version.cpp.obj:' in line or 'version.cpp.o:' in line)]
            if len(edges)!=2 or any(dependency.relative_to(work/'build').as_posix() not in e.replace('\\','/') for e in edges):
                raise RuntimeError('OBJECT_DEPENDS absent from a real object edge: '+repr(edges))
            ok=matched != mismatch
            outcomes.append({'name':name,'accepted':ok,'comparison_rows':table.rows,'version_commands':version,'object_edges':edges})
            if not ok: raise RuntimeError('comparator failed the '+name+' control')
            print('[PASS] nonempty source-property '+name+' control',flush=True)
    finally:
        save(root,records)
        (root/'results.json').write_text(json.dumps(outcomes,indent=2)+'\n',encoding='utf-8')
    return 0

if __name__=='__main__':
    raise SystemExit(main())
