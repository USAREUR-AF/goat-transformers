cmake_minimum_required(VERSION 3.16)
project(goat_transformers_cpp VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

get_filename_component(GT_REPO_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../.." ABSOLUTE)
set(GT_PACKS_DIR "${GT_REPO_ROOT}/packs" CACHE PATH "Directory of packs the tests load; model modules are read from ../model beside it")

if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
  set(GT_WARNINGS -Wall -Wextra -Wpedantic)
endif()

add_library(goat_transformers STATIC
  src/codecs.cpp
  src/derive.cpp
  src/engine.cpp
  src/json.cpp
  src/jsonwire.cpp
  src/pack.cpp
  src/protobuf.cpp
  src/sequential.cpp
  src/transforms.cpp
  src/util.cpp
  src/xml.cpp)
target_include_directories(goat_transformers
  PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include
  PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src)
target_compile_options(goat_transformers PRIVATE ${GT_WARNINGS})

add_executable(goat-xf cli/main.cpp)
target_link_libraries(goat-xf PRIVATE goat_transformers)
target_compile_options(goat-xf PRIVATE ${GT_WARNINGS})

enable_testing()

add_executable(goat_transformers_vectors tests/vectors_test.cpp)
target_link_libraries(goat_transformers_vectors PRIVATE goat_transformers)
target_include_directories(goat_transformers_vectors PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src)
target_compile_definitions(goat_transformers_vectors PRIVATE GT_PACKS_DIR="${GT_PACKS_DIR}")
target_compile_options(goat_transformers_vectors PRIVATE ${GT_WARNINGS})
add_test(NAME vectors COMMAND goat_transformers_vectors)

add_executable(goat_transformers_unit tests/unit_test.cpp)
target_link_libraries(goat_transformers_unit PRIVATE goat_transformers)
target_include_directories(goat_transformers_unit PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src)
target_compile_options(goat_transformers_unit PRIVATE ${GT_WARNINGS})
add_test(NAME unit COMMAND goat_transformers_unit)

add_test(NAME cli_list_formats COMMAND goat-xf list-formats --packs ${GT_PACKS_DIR})
add_test(NAME cli_packs_only COMMAND goat-xf list-formats --packs ${GT_PACKS_DIR} --packs-only cot-xml,geojson)
