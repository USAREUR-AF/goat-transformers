cmake_minimum_required(VERSION 3.16)
project(goat_transformers_cpp VERSION 0.8.0 LANGUAGES CXX)

# Three ways to consume the library target goat_transformers::goat_transformers:
#   add_subdirectory(<this directory>)          the library only; no tests, no tool
#   FetchContent with SOURCE_SUBDIR engines/cpp  the same, from the repository
#   cmake --install, then find_package(goat_transformers 0.8 CONFIG)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# The tests and the command-line tool are built when this is the top-level
# project, and left out when another project adds this directory.
if(CMAKE_SOURCE_DIR STREQUAL CMAKE_CURRENT_SOURCE_DIR)
  set(GT_TOP_LEVEL ON)
else()
  set(GT_TOP_LEVEL OFF)
endif()
option(GT_BUILD_TESTS "Build the conformance and unit tests" ${GT_TOP_LEVEL})
option(GT_BUILD_CLI "Build the goat-xf command-line tool" ${GT_TOP_LEVEL})
option(GT_INSTALL "Add the install and package-config rules" ${GT_TOP_LEVEL})

get_filename_component(GT_REPO_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../.." ABSOLUTE)
set(GT_PACKS_DIR "${GT_REPO_ROOT}/packs" CACHE PATH "Directory of packs the tests load; model modules are read from ../model beside it")

if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
  set(GT_WARNINGS -Wall -Wextra -Wpedantic)
endif()

# AddressSanitizer and UndefinedBehaviorSanitizer on every target; a finding
# stops the test that reached it.
option(GT_SANITIZE "Build with -fsanitize=address,undefined" OFF)
if(GT_SANITIZE)
  add_compile_options(-fsanitize=address,undefined -fno-sanitize-recover=undefined -fno-omit-frame-pointer -g)
  add_link_options(-fsanitize=address,undefined)
endif()

# The wires of the build (engine-spec.md, Version 0.24): a list of xml, geojson,
# json, bits, protobuf, text and tlv, separated by ';' or ','. Empty, the
# default, names no set: all seven. The codec of a wire not in the set is left
# out of the library; a pack on that wire is refused with unknown-wire.
set(GT_ALL_WIRES xml geojson json bits protobuf text tlv)
set(GT_WIRES "" CACHE STRING "Wires to build, from: xml geojson json bits protobuf text tlv (empty: all seven)")
string(REPLACE "," ";" GT_WIRE_SET "${GT_WIRES}")
string(STRIP "${GT_WIRE_SET}" GT_WIRE_SET)
if(GT_WIRE_SET STREQUAL "")
  set(GT_WIRE_SET ${GT_ALL_WIRES})
endif()
foreach(w IN LISTS GT_WIRE_SET)
  string(STRIP "${w}" w_stripped)
  if(NOT w_stripped IN_LIST GT_ALL_WIRES)
    message(FATAL_ERROR "GT_WIRES: '${w}' is not a wire; the wires are ${GT_ALL_WIRES}")
  endif()
endforeach()
set(GT_WIRE_DEFINITIONS "")
set(GT_ALL_WIRES_BUILT ON)
foreach(w IN LISTS GT_ALL_WIRES)
  string(TOUPPER "${w}" W)
  set(GT_HAS_${W} OFF)
  foreach(x IN LISTS GT_WIRE_SET)
    string(STRIP "${x}" x)
    if(x STREQUAL w)
      set(GT_HAS_${W} ON)
    endif()
  endforeach()
  if(GT_HAS_${W})
    list(APPEND GT_WIRE_DEFINITIONS GT_WIRE_${W}=1)
  else()
    list(APPEND GT_WIRE_DEFINITIONS GT_WIRE_${W}=0)
    set(GT_ALL_WIRES_BUILT OFF)
  endif()
endforeach()
message(STATUS "goat_transformers wires: ${GT_WIRE_DEFINITIONS}")

set(GT_SOURCES
  src/codecs.cpp
  src/derive.cpp
  src/engine.cpp
  src/exact.cpp
  src/linecheck.cpp
  src/pack.cpp
  src/sequential.cpp
  src/transforms.cpp
  src/util.cpp)
# The JSON reader and the items of a JSON array serve json and geojson.
if(GT_HAS_JSON OR GT_HAS_GEOJSON)
  list(APPEND GT_SOURCES src/json.cpp src/jsonwire.cpp)
endif()
if(GT_HAS_XML)
  list(APPEND GT_SOURCES src/xml.cpp)
endif()
if(GT_HAS_PROTOBUF)
  list(APPEND GT_SOURCES src/protobuf.cpp)
endif()
if(GT_HAS_TEXT)
  list(APPEND GT_SOURCES src/text.cpp)
endif()
if(GT_HAS_TLV)
  list(APPEND GT_SOURCES src/tlv.cpp)
endif()

add_library(goat_transformers STATIC ${GT_SOURCES})
target_compile_definitions(goat_transformers PRIVATE ${GT_WIRE_DEFINITIONS})
add_library(goat_transformers::goat_transformers ALIAS goat_transformers)
target_include_directories(goat_transformers
  PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>
  PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src)
target_compile_features(goat_transformers PUBLIC cxx_std_17)
target_compile_options(goat_transformers PRIVATE ${GT_WARNINGS})

if(GT_BUILD_CLI)
  add_executable(goat-xf cli/main.cpp)
  target_link_libraries(goat-xf PRIVATE goat_transformers)
  target_compile_options(goat-xf PRIVATE ${GT_WARNINGS})

  # The benchmark (engine-spec.md 0.25, ruling 2), run from the repository
  # root: goat-bench bench/set.json. It reads the set with the library's JSON
  # reader, which a build without json and geojson does not have.
  set(GT_BENCH_JSON "")
  if(NOT (GT_HAS_JSON OR GT_HAS_GEOJSON))
    set(GT_BENCH_JSON src/json.cpp)
  endif()
  add_executable(goat-bench cli/bench.cpp ${GT_BENCH_JSON})
  target_link_libraries(goat-bench PRIVATE goat_transformers)
  target_include_directories(goat-bench PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src)
  target_compile_options(goat-bench PRIVATE ${GT_WARNINGS})
endif()

if(GT_INSTALL)
  include(GNUInstallDirs)
  include(CMakePackageConfigHelpers)
  set(GT_CONFIG_DIR "${CMAKE_INSTALL_LIBDIR}/cmake/goat_transformers")
  install(TARGETS goat_transformers EXPORT goat_transformersTargets
    ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR}
    INCLUDES DESTINATION include)
  install(DIRECTORY include/ DESTINATION include)
  install(EXPORT goat_transformersTargets NAMESPACE goat_transformers:: DESTINATION ${GT_CONFIG_DIR})
  file(WRITE "${CMAKE_CURRENT_BINARY_DIR}/goat_transformersConfig.cmake"
    "include(\"\${CMAKE_CURRENT_LIST_DIR}/goat_transformersTargets.cmake\")\n")
  write_basic_package_version_file("${CMAKE_CURRENT_BINARY_DIR}/goat_transformersConfigVersion.cmake"
    VERSION ${PROJECT_VERSION} COMPATIBILITY SameMinorVersion)
  install(FILES
    "${CMAKE_CURRENT_BINARY_DIR}/goat_transformersConfig.cmake"
    "${CMAKE_CURRENT_BINARY_DIR}/goat_transformersConfigVersion.cmake"
    DESTINATION ${GT_CONFIG_DIR})
  if(GT_BUILD_CLI)
    install(TARGETS goat-xf RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR})
  endif()
endif()

if(GT_BUILD_TESTS)
  enable_testing()

  # The test programs read vector files with the library's JSON reader; a
  # build without json and geojson does not have it in the library.
  set(GT_TEST_JSON "")
  if(NOT (GT_HAS_JSON OR GT_HAS_GEOJSON))
    set(GT_TEST_JSON src/json.cpp)
  endif()

  # In a build with fewer wires, `vectors` is the reduced-build check (README.md,
  # Wires of a build): the packs on the build's wires, the vectors among them,
  # and every pack on another wire refused with unknown-wire.
  add_executable(goat_transformers_vectors tests/vectors_test.cpp ${GT_TEST_JSON})
  target_link_libraries(goat_transformers_vectors PRIVATE goat_transformers)
  target_include_directories(goat_transformers_vectors PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src)
  target_compile_definitions(goat_transformers_vectors PRIVATE GT_PACKS_DIR="${GT_PACKS_DIR}")
  target_compile_options(goat_transformers_vectors PRIVATE ${GT_WARNINGS})
  add_test(NAME vectors COMMAND goat_transformers_vectors)
endif()

# The other tests load every pack of the repository: a build with all seven wires.
if(GT_BUILD_TESTS AND GT_ALL_WIRES_BUILT)

  # Malformed input (engine-spec.md 0.8): every vector input cut short and with
  # single bytes changed. Run it in a build with -DGT_SANITIZE=ON as well.
  add_executable(goat_transformers_fuzz tests/fuzz_test.cpp)
  target_link_libraries(goat_transformers_fuzz PRIVATE goat_transformers)
  target_include_directories(goat_transformers_fuzz PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src)
  target_compile_definitions(goat_transformers_fuzz PRIVATE GT_PACKS_DIR="${GT_PACKS_DIR}")
  target_compile_options(goat_transformers_fuzz PRIVATE ${GT_WARNINGS})
  add_test(NAME malformed_input COMMAND goat_transformers_fuzz)

  add_executable(goat_transformers_unit tests/unit_test.cpp)
  target_link_libraries(goat_transformers_unit PRIVATE goat_transformers)
  target_include_directories(goat_transformers_unit PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src)
  target_compile_options(goat_transformers_unit PRIVATE ${GT_WARNINGS})
  add_test(NAME unit COMMAND goat_transformers_unit)

  # What an engine keeps (engine-spec.md 0.25, ruling 1): results on a used
  # instance, after failures, and from eight threads at once.
  find_package(Threads REQUIRED)
  add_executable(goat_transformers_parse_once tests/parse_once_test.cpp)
  target_link_libraries(goat_transformers_parse_once PRIVATE goat_transformers Threads::Threads)
  target_include_directories(goat_transformers_parse_once PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src)
  target_compile_definitions(goat_transformers_parse_once PRIVATE GT_PACKS_DIR="${GT_PACKS_DIR}"
                             GT_REPO_ROOT="${GT_REPO_ROOT}")
  target_compile_options(goat_transformers_parse_once PRIVATE ${GT_WARNINGS})
  add_test(NAME parse_once COMMAND goat_transformers_parse_once)

  if(GT_BUILD_CLI)
    add_test(NAME cli_list_formats COMMAND goat-xf list-formats --packs ${GT_PACKS_DIR})
    add_test(NAME cli_packs_only COMMAND goat-xf list-formats --packs ${GT_PACKS_DIR} --packs-only cot-xml,geojson)
    # The tool vectors of the command-line contract (engine-spec.md 0.23), run
    # by the repository's runner from the repository's root.
    find_package(Python3 COMPONENTS Interpreter QUIET)
    if(Python3_Interpreter_FOUND AND EXISTS "${GT_REPO_ROOT}/tools/tool-vectors.py")
      add_test(NAME tool_vectors
        COMMAND ${Python3_EXECUTABLE} -I "${GT_REPO_ROOT}/tools/tool-vectors.py" -- $<TARGET_FILE:goat-xf>
        WORKING_DIRECTORY "${GT_REPO_ROOT}")
    endif()
  endif()
endif()
