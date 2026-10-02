// ClipMesh Finder Share extension (com.apple.share-services).
//
// Built as a sandboxed MH_EXECUTE app extension (entry point _NSExtensionMain).
// It never asks anything: it collects the shared file URLs, hands them to the
// ClipMesh app through clipmesh-share://send?f=<path>&f=<path>… and completes.
#import <Cocoa/Cocoa.h>
#import <QuartzCore/QuartzCore.h>

static NSString *const CMFileURLType = @"public.file-url";
static NSString *const CMURLType = @"public.url";
// LaunchServices comfortably handles long URLs, but very large selections fall
// back to the legacy manifest form, which the app keeps supporting.
static const NSUInteger CMMaxInlineURLLength = 48 * 1024;

@interface ClipMeshShareController : NSViewController
@end

@implementation ClipMeshShareController {
    NSMutableArray<NSURL *> *_files;
    BOOL _started;
    BOOL _finished;
}

- (void)loadView {
    NSView *view = [[NSView alloc] initWithFrame:NSMakeRect(0, 0, 240, 56)];
    view.appearance = [NSAppearance appearanceNamed:NSAppearanceNameDarkAqua];
    view.wantsLayer = YES;
    view.layer.backgroundColor = [NSColor colorWithSRGBRed:0x13 / 255.0 green:0x13 / 255.0 blue:0x14 / 255.0 alpha:1].CGColor;

    NSView *dot = [[NSView alloc] initWithFrame:NSMakeRect(20, 23, 10, 10)];
    dot.wantsLayer = YES;
    dot.layer.cornerRadius = 5;
    dot.layer.backgroundColor = [NSColor colorWithSRGBRed:0xE5 / 255.0 green:0x5F / 255.0 blue:0x11 / 255.0 alpha:1].CGColor;
    CABasicAnimation *pulse = [CABasicAnimation animationWithKeyPath:@"opacity"];
    pulse.fromValue = @1.0;
    pulse.toValue = @0.35;
    pulse.duration = 0.6;
    pulse.autoreverses = YES;
    pulse.repeatCount = HUGE_VALF;
    [dot.layer addAnimation:pulse forKey:@"pulse"];
    [view addSubview:dot];

    NSTextField *label = [NSTextField labelWithString:@"Sending to ClipMesh…"];
    label.font = [NSFont fontWithName:@"Sora-Medium" size:14] ?: [NSFont systemFontOfSize:14 weight:NSFontWeightMedium];
    label.textColor = NSColor.whiteColor;
    label.frame = NSMakeRect(40, 18, 190, 20);
    [view addSubview:label];

    self.view = view;
    self.preferredContentSize = view.frame.size;
}

- (void)beginRequestWithExtensionContext:(NSExtensionContext *)context {
    [super beginRequestWithExtensionContext:context];
    [self collectFromContext:context];
}

- (void)viewDidAppear {
    [super viewDidAppear];
    // Older hosts may not route through beginRequestWithExtensionContext:.
    if (self.extensionContext) [self collectFromContext:self.extensionContext];
}

+ (NSURL *)urlFromValue:(id)value {
    if ([value isKindOfClass:NSURL.class]) return (NSURL *)value;
    if ([value isKindOfClass:NSData.class]) return [NSURL URLWithDataRepresentation:(NSData *)value relativeToURL:nil];
    if ([value isKindOfClass:NSString.class]) return [NSURL URLWithString:(NSString *)value];
    return nil;
}

- (void)addFile:(NSURL *)url {
    if (!url.isFileURL) return;
    @synchronized (self) {
        [_files addObject:url];
    }
}

- (void)collectFromContext:(NSExtensionContext *)context {
    @synchronized (self) {
        if (_started) return;
        _started = YES;
        _files = [NSMutableArray array];
    }
    dispatch_group_t group = dispatch_group_create();
    for (NSExtensionItem *item in context.inputItems) {
        for (NSItemProvider *provider in item.attachments) {
            NSString *urlType = nil;
            if ([provider hasItemConformingToTypeIdentifier:CMFileURLType]) urlType = CMFileURLType;
            else if ([provider hasItemConformingToTypeIdentifier:CMURLType]) urlType = CMURLType;
            if (urlType) {
                dispatch_group_enter(group);
                [provider loadItemForTypeIdentifier:urlType options:nil completionHandler:^(id<NSSecureCoding> value, NSError *error) {
                    [self addFile:[ClipMeshShareController urlFromValue:(id)value]];
                    dispatch_group_leave(group);
                }];
                continue;
            }
            // Content without a file URL (for example an image shared from Photos):
            // keep a private copy that the ClipMesh app can read and send.
            NSString *dataType = nil;
            for (NSString *candidate in @[@"public.image", @"public.movie", @"public.data"]) {
                if ([provider hasItemConformingToTypeIdentifier:candidate]) { dataType = candidate; break; }
            }
            if (!dataType) continue;
            dispatch_group_enter(group);
            [provider loadFileRepresentationForTypeIdentifier:dataType completionHandler:^(NSURL *url, NSError *error) {
                if (url) {
                    NSString *folder = [NSTemporaryDirectory() stringByAppendingPathComponent:[@"ClipMeshShare-" stringByAppendingString:NSUUID.UUID.UUIDString]];
                    [NSFileManager.defaultManager createDirectoryAtPath:folder withIntermediateDirectories:YES attributes:nil error:nil];
                    NSURL *copy = [NSURL fileURLWithPath:[folder stringByAppendingPathComponent:url.lastPathComponent]];
                    if ([NSFileManager.defaultManager copyItemAtURL:url toURL:copy error:nil]) [self addFile:copy];
                }
                dispatch_group_leave(group);
            }];
        }
    }
    dispatch_group_notify(group, dispatch_get_main_queue(), ^{ [self handOff]; });
}

- (NSURL *)manifestURLForFiles:(NSArray<NSURL *> *)files {
    NSString *path = [NSTemporaryDirectory() stringByAppendingPathComponent:[NSString stringWithFormat:@"clipmesh-share-%@.txt", NSUUID.UUID.UUIDString]];
    NSMutableString *body = [NSMutableString string];
    for (NSURL *url in files) [body appendFormat:@"%@\n", url.path];
    if (![body writeToFile:path atomically:YES encoding:NSUTF8StringEncoding error:nil]) return nil;
    NSURLComponents *components = [NSURLComponents componentsWithString:@"clipmesh-share://send"];
    components.queryItems = @[[NSURLQueryItem queryItemWithName:@"manifest" value:path]];
    return components.URL;
}

- (void)handOff {
    if (_finished) return;
    _finished = YES;
    NSArray<NSURL *> *files;
    @synchronized (self) {
        files = [_files copy];
    }
    if (files.count == 0) {
        [self.extensionContext cancelRequestWithError:[NSError errorWithDomain:NSCocoaErrorDomain code:NSUserCancelledError userInfo:nil]];
        return;
    }
    // ASCII-only allowed set so NSURL never rejects non-ASCII file names.
    NSCharacterSet *allowed = [NSCharacterSet characterSetWithCharactersInString:
        @"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~/"];
    NSMutableArray<NSString *> *parts = [NSMutableArray arrayWithCapacity:files.count];
    for (NSURL *url in files) {
        NSString *encoded = [url.path stringByAddingPercentEncodingWithAllowedCharacters:allowed];
        if (encoded.length) [parts addObject:[@"f=" stringByAppendingString:encoded]];
    }
    NSString *query = [parts componentsJoinedByString:@"&"];
    NSURL *target = nil;
    if (query.length > 0 && query.length <= CMMaxInlineURLLength) {
        target = [NSURL URLWithString:[@"clipmesh-share://send?" stringByAppendingString:query]];
    }
    if (!target) target = [self manifestURLForFiles:files];
    if (target) [NSWorkspace.sharedWorkspace openURL:target];
    [self.extensionContext completeRequestReturningItems:@[] completionHandler:nil];
}

@end
