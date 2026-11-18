// SPDX-License-Identifier: BSD-2-Clause-Patent
// penang: the OS side of UniXNU-sheng's package/AppleARMBacklight.cpp, without its KTZ8866 / GENI I2C transport (boot argument
// backlight=1). The g53's panel keeps the backlight level its firmware set; this service publishes what iPadOS 27 needs to create the
// built-in display and accepts brightness requests (recorded in penang_backlight_stats, not yet written to the panel).
// From sheng's notes, unchanged: CoreBrightness (backboardd) finds the backlight by backlight-control = true and takes it for the built-in
// display only when IOObjectConformsTo(service, "AppleARMBacklight") holds; only then does it start the libEDR server that QuartzCore's
// IOMFBServer sends to synchronously once backlight-control makes CADeviceHasBacklight true (published without the conformance, the send
// blocked with the display server lock held). CoreBrightness's Display.m fails without backlight-marketing-table and
// backlight-calibration-parameters; BrightnessControl reads LmaxProduct as 4 bytes of 16.16 and LmidProduct / LminProduct as numbers.
// The class cannot be called AppleARMBacklight (AppleARMPlatform defines it); getMetaClass answers that metaclass instead, and
// NativeSandboxGrantProcess lets backboardd set its properties past its sandbox profile.
#include <IOKit/IOService.h>
#include <IOKit/IOLib.h>
#include <IOKit/IOPlatformExpert.h>
#include <libkern/c++/OSNumber.h>
#include <libkern/c++/OSDictionary.h>
#include <libkern/c++/OSData.h>
#include <libkern/c++/OSSymbol.h>
#include <pexpert/pexpert.h>

// [0] stage (1 allocated, 3 published, 4 published as AppleARMBacklight, negative: failed), [1] brightness requests, [2] last level asked,
// [3] last request in signed 16.16 nits
extern "C" {volatile int32_t penang_backlight_stats[4];}

namespace {
constexpr uint32_t kMaxLevel = 2047;
// The range sheng publishes (not measured on the g53 either): it only sets the slider's scale.
constexpr uint32_t kMinNits = 2, kMidNits = 140, kMaxNits = 500;
}

class PenangBacklight : public IOService {
    OSDeclareDefaultStructors(PenangBacklight)
    uint32_t level = kMaxLevel / 2;
    void publish(uint32_t value) {
        OSDictionary *brightness = OSDictionary::withCapacity(3), *milliNits = OSDictionary::withCapacity(3), *parameters = OSDictionary::withCapacity(2);
        OSNumber *min = OSNumber::withNumber(0ULL, 32), *max = OSNumber::withNumber(kMaxLevel, 32), *current = OSNumber::withNumber(value, 32);
        OSNumber *minMilli = OSNumber::withNumber(kMinNits * 1000ULL, 32), *maxMilli = OSNumber::withNumber(kMaxNits * 1000ULL, 32);
        OSNumber *currentMilli = OSNumber::withNumber((uint64_t)value * kMaxNits * 1000 / kMaxLevel, 32);
        if (brightness && milliNits && parameters && min && max && current && minMilli && maxMilli && currentMilli) {
            brightness->setObject("min", min); brightness->setObject("max", max); brightness->setObject("value", current);
            milliNits->setObject("min", minMilli); milliNits->setObject("max", maxMilli); milliNits->setObject("value", currentMilli);
            parameters->setObject("brightness", brightness);
            parameters->setObject("BrightnessMilliNits", milliNits);
            setProperty("IODisplayParameters", parameters);
        }
        OSSafeReleaseNULL(min); OSSafeReleaseNULL(max); OSSafeReleaseNULL(current); OSSafeReleaseNULL(minMilli); OSSafeReleaseNULL(maxMilli);
        OSSafeReleaseNULL(currentMilli); OSSafeReleaseNULL(brightness); OSSafeReleaseNULL(milliNits); OSSafeReleaseNULL(parameters);
    }
    void publishCalibration() {
        const int32_t table[] = {(int32_t)(kMinNits << 16), (int32_t)(kMidNits << 16), (int32_t)(kMaxNits << 16)};
        if (OSData *marketing = OSData::withBytes(table, sizeof table)) {setProperty("backlight-marketing-table", marketing); marketing->release();}
        if (OSData *value = OSData::withBytes(&table[2], sizeof table[2])) {setProperty("LmaxProduct", value); value->release();}
        const struct {const char *key; uint32_t nits;} products[] = {{"LminProduct", kMinNits}, {"LmidProduct", kMidNits}};
        for (const auto &product : products)
            if (OSNumber *value = OSNumber::withNumber(product.nits, 32)) {setProperty(product.key, value); value->release();}
        OSDictionary *calibration = OSDictionary::withCapacity(6);
        if (!calibration) return;
        const struct {const char *key; uint32_t nits;} fields[] = {{"lMinProduct", kMinNits}, {"lMidProduct", kMidNits}, {"lMaxProduct", kMaxNits},
                                                                   {"lMinPanel", kMinNits}, {"lMidPanel", kMidNits}, {"lMaxPanel", kMaxNits}};
        for (const auto &field : fields)
            if (OSNumber *number = OSNumber::withNumber((uint64_t)field.nits << 16, 32)) {calibration->setObject(field.key, number); number->release();}
        setProperty("backlight-calibration-parameters", calibration);
        calibration->release();
    }
public:
    static inline const OSMetaClass *gAppleClass = nullptr;
    static inline bool gImpersonating = false;
    bool impersonate() {
        const OSSymbol *name = OSSymbol::withCString("AppleARMBacklight");
        gAppleClass = name ? OSMetaClass::getMetaClassWithName(name) : nullptr;
        OSSafeReleaseNULL(name);
        if (!gAppleClass) return false;
        __atomic_store_n(&gImpersonating, true, __ATOMIC_RELEASE);
        return true;
    }
    bool publishBacklight() {
        uint32_t control = 1;
        PE_parse_boot_argn("backlight-control", &control, sizeof control);
        if (control == 1 && impersonate()) {setProperty("NativeSandboxGrantProcess", "backboardd"); setProperty("backlight-control", true);}
        const bool impersonated = control == 1 && gAppleClass;
        publishCalibration();
        publish(level);
        registerService();
        penang_backlight_stats[0] = impersonated ? 4 : 3;
        IOLog("penang backlight: published%s\n", impersonated ? " as AppleARMBacklight" : " (no AppleARMBacklight class: backlight-control left out)");
        return true;
    }
    static uint32_t levelForNits(int32_t fixed) {
        if (fixed <= 0) return 0;
        const uint64_t scale = (uint64_t)kMaxNits << 16;
        const uint64_t scaled = ((uint64_t)fixed * kMaxLevel + scale / 2) / scale;
        return scaled < 1 ? 1 : scaled > kMaxLevel ? kMaxLevel : (uint32_t)scaled;
    }
    IOReturn setProperties(OSObject *properties) override {
        OSDictionary *dictionary = OSDynamicCast(OSDictionary, properties);
        if (!dictionary) return kIOReturnBadArgument;
        uint32_t goal;
        if (OSNumber *nits = OSDynamicCast(OSNumber, dictionary->getObject("brightness-nits"))) {
            penang_backlight_stats[3] = (int32_t)nits->unsigned32BitValue();
            goal = levelForNits((int32_t)nits->unsigned32BitValue());
        } else if (OSNumber *brightness = OSDynamicCast(OSNumber, dictionary->getObject("brightness"))) {
            const int32_t requested = (int32_t)brightness->unsigned32BitValue();
            goal = requested < 0 ? 0 : (uint32_t)requested > kMaxLevel ? kMaxLevel : (uint32_t)requested;
        } else {
            return kIOReturnSuccess;
        }
        __atomic_fetch_add(&penang_backlight_stats[1], 1, __ATOMIC_RELAXED);
        penang_backlight_stats[2] = (int32_t)goal;
        level = goal;
        publish(goal);
        return kIOReturnSuccess;
    }
};
// OSDefineMetaClassAndStructors(PenangBacklight, IOService) with getMetaClass answering the AppleARMBacklight metaclass after impersonate()
// (as sheng's ShengBacklight on arm64e: a signed vtable cannot be copied).
PenangBacklight::MetaClass PenangBacklight::gMetaClass;
const OSMetaClass * const PenangBacklight::metaClass = &PenangBacklight::gMetaClass;
const OSMetaClass * const PenangBacklight::superClass = &IOService::gMetaClass;
PenangBacklight::PenangBacklight(const OSMetaClass *meta) : IOService(meta) {}
PenangBacklight::~PenangBacklight() {}
const OSMetaClass *PenangBacklight::getMetaClass() const
{
    return __atomic_load_n(&gImpersonating, __ATOMIC_ACQUIRE) && gAppleClass ? gAppleClass : &gMetaClass;
}
OSMetaClassConstructorInit(PenangBacklight, IOService, )
OSDefineDefaultStructors(PenangBacklight, IOService)

// Called by the display's late probe (LegacyDisplayProbe.cpp) with backlight=1, once this file's class is registered (its static
// initializer runs between the display probe's preModLoad and postModLoad).
extern "C" void penang_backlight_start(void) {
    PenangBacklight *backlight = OSTypeAlloc(PenangBacklight);
    penang_backlight_stats[0] = 1;
    if (!backlight || !backlight->init() || !backlight->attach(IOService::getPlatform()) || !backlight->start(IOService::getPlatform()) ||
        !backlight->publishBacklight()) {
        if (backlight) backlight->release();
        penang_backlight_stats[0] = -1;
        IOLog("penang backlight: start failed\n");
        return;
    }
    backlight->release();
}
