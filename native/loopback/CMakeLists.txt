cmake_minimum_required(VERSION 3.20)
project(capption_loopback CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
# Static CRT: the helper ships as a single exe next to the app.
set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")

add_executable(capption-loopback main.cpp)
target_compile_definitions(capption-loopback PRIVATE UNICODE _UNICODE NOMINMAX _WIN32_WINNT=0x0A00)
target_compile_options(capption-loopback PRIVATE /W4 /permissive-)
target_link_libraries(capption-loopback PRIVATE mmdevapi ole32)
