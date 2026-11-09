/*
 *
 *    Copyright (c) 2021 Project CHIP Authors
 *    All rights reserved.
 *
 *    Licensed under the Apache License, Version 2.0 (the "License");
 *    you may not use this file except in compliance with the License.
 *    You may obtain a copy of the License at
 *
 *        http://www.apache.org/licenses/LICENSE-2.0
 *
 *    Unless required by applicable law or agreed to in writing, software
 *    distributed under the License is distributed on an "AS IS" BASIS,
 *    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 *    See the License for the specific language governing permissions and
 *    limitations under the License.
 */

/**
 *    @file
 *          Example project configuration file for CHIP.
 *
 *          This is a place to put application or project-specific overrides
 *          to the default configuration values for general CHIP features.
 *
 */

#pragma once

// --- Reproducible builds -----------------------------------------------------
//
// CHIPDeviceConfig.h defines these two as __DATE__ / __TIME__ behind an
// #ifndef, with the comment "Useful for deterministic builds" -- overriding
// them here is the intended mechanism, not a workaround.
//
// Without this, the compiled firmware embeds the wall-clock time and two
// builds of the same commit produce different .a and .elf hashes, so an SBOM
// cannot be used to verify a shipped binary.
//
// The values must stay parseable by src/include/platform/BuildTime.h:
//   date: "Mmm DD YYYY", 11 chars, day space-padded ("Jan  1 1970")
//   time: "HH:MM:SS", 8 chars
// Changing the shape breaks COMPUTE_BUILD_YEAR/DAY/MONTH at compile time.
#define CHIP_DEVICE_CONFIG_FIRMWARE_BUILD_DATE "Jan  1 1970"
#define CHIP_DEVICE_CONFIG_FIRMWARE_BUILD_TIME "00:00:00"

// Use a default pairing code if one hasn't been provisioned in flash.
#define CHIP_DEVICE_CONFIG_USE_TEST_SETUP_PIN_CODE 20202021
#define CHIP_DEVICE_CONFIG_USE_TEST_SETUP_DISCRIMINATOR 0xF00

//  Switching from Thread child to router may cause a few second packet stall.
//  Until this is improved in OpenThread we need to increase the retransmission
//  interval to survive the stall.
#define CHIP_CONFIG_MRP_LOCAL_ACTIVE_RETRY_INTERVAL (1000_ms32)

// ========== Multicast groups Configuration Overrides =========
#undef CHIP_CONFIG_MAX_GROUP_ENDPOINTS_PER_FABRIC
#define CHIP_CONFIG_MAX_GROUP_ENDPOINTS_PER_FABRIC 2

#define CHIP_CONFIG_EXAMPLE_ACCESS_CONTROL_MAX_SUBJECTS_PER_ENTRY (4 * CHIP_CONFIG_MAX_GROUP_ENDPOINTS_PER_FABRIC)
