class Demo:
    DISP_CONF_MIN = int(os.getenv("DISP_CONF_MIN", 0))
    DISP_CONF_MAX = int(os.getenv("DISP_CONF_MAX", 255))
    SIGMA_MIN = int(os.getenv("SIGMA_MIN", 0))
    SIGMA_MAX = int(os.getenv("SIGMA_MAX", 250))
    LRCT_MIN = int(os.getenv("LRCT_MIN", 0))
    LRCT_MAX = int(os.getenv("LRCT_MAX", 10))
    error = None

    def run_all(self, conf):
        if conf.args.app is not None:
            app = App(appName=conf.args.app)
            self.onAppSetup(app)
            app.createVenv()
            self.onAppStart(app)
            app.runApp(shouldRun=self.shouldRun)
        else:
            self.setup(conf)
            self.run()

    def __init__(self, displayFrames=True,
                       onNewFrame = noop,
                       onShowFrame = noop,
                       onNn = noop,
                       onReport = noop,
                       onSetup = noop,
                       onTeardown = noop,
                       onIter = noop,
                       onAppSetup = noop,
                       onAppStart = noop,
                       shouldRun = lambda: True,
                       showDownloadProgress=None,
                       collectMetrics=False):

        self._openvinoVersion = None
        self._displayFrames = displayFrames
        self.toggleMetrics(collectMetrics)
        self.onNewFrame = onNewFrame
        self.onShowFrame = onShowFrame
        self.onNn = onNn
        self.onReport = onReport
        self.onSetup = onSetup
        self.onTeardown = onTeardown
        self.onIter = onIter
        self.shouldRun = shouldRun
        self.showDownloadProgress = showDownloadProgress
        self.onAppSetup = onAppSetup
        self.onAppStart = onAppStart

    def setCallbacks(self, onNewFrame=None,
                           onShowFrame=None,
                           onNn=None,
                           onReport=None,
                           onSetup=None,
                           onTeardown=None,
                           onIter=None,
                           onAppSetup=None,
                           onAppStart=None,
                           shouldRun=None,
                           showDownloadProgress=None):

        if onNewFrame is not None:
            self.onNewFrame = onNewFrame
        if onShowFrame is not None:
            self.onShowFrame = onShowFrame
        if onNn is not None:
            self.onNn = onNn
        if onReport is not None:
            self.onReport = onReport
        if onSetup is not None:
            self.onSetup = onSetup
        if onTeardown is not None:
            self.onTeardown = onTeardown
        if onIter is not None:
            self.onIter = onIter
        if shouldRun is not None:
            self.shouldRun = shouldRun
        if showDownloadProgress is not None:
            self.showDownloadProgress = showDownloadProgress
        if onAppSetup is not None:
            self.onAppSetup = onAppSetup
        if onAppStart is not None:
            self.onAppStart = onAppStart

    def toggleMetrics(self, enabled):
        if enabled:
            self.metrics = MetricManager()
        else:
            self.metrics = None

    def setup(self, conf: ConfigManager):
        print("Setting up demo...")
        self._conf = conf
        self._rgbRes = conf.getRgbResolution()
        self._monoRes = conf.getMonoResolution()
        if self._conf.args.openvinoVersion:
            self._openvinoVersion = getattr(dai.OpenVINO.Version, 'VERSION_' + self._conf.args.openvinoVersion)
        self._deviceInfo = getDeviceInfo(self._conf.args.deviceId, args.debug)
        if self._conf.args.reportFile:
            reportFileP = Path(self._conf.args.reportFile).with_suffix('.csv')
            reportFileP.parent.mkdir(parents=True, exist_ok=True)
            self._reportFile = reportFileP.open('a')
        self._pm = PipelineManager(openvinoVersion=self._openvinoVersion, lowCapabilities=self._conf.lowCapabilities)

        if self._conf.args.xlinkChunkSize is not None:
            self._pm.setXlinkChunkSize(self._conf.args.xlinkChunkSize)

        self._nnManager = None
        if self._conf.useNN:
            self._blobManager = BlobManager(
                zooDir=DEPTHAI_ZOO,
                zooName=self._conf.getModelName(),
                progressFunc=self.showDownloadProgress
            )
            self._nnManager = NNetManager(inputSize=self._conf.inputSize, sync=self._conf.args.sync)

            if self._conf.getModelDir() is not None:
                configPath = self._conf.getModelDir() / Path(self._conf.getModelName()).with_suffix(f".json")
                self._nnManager.readConfig(configPath)

            self._nnManager.countLabel(self._conf.getCountLabel(self._nnManager))
            self._pm.setNnManager(self._nnManager)

        self._device = dai.Device(self._pm.pipeline.getOpenVINOVersion(), self._deviceInfo, usb2Mode=self._conf.args.usbSpeed == "usb2")
        self._device.addLogCallback(self._logMonitorCallback)
        if sentryEnabled:
            try:
                from sentry_sdk import set_user
                set_user({"mxid": self._device.getMxId()})
            except:
                pass
        if self.metrics is not None:
            self.metrics.reportDevice(self._device)
        if self._deviceInfo.desc.protocol == dai.XLinkProtocol.X_LINK_USB_VSC:
            print("USB Connection speed: {}".format(self._device.getUsbSpeed()))
        self._conf.adjustParamsToDevice(self._device)
        self._conf.adjustPreviewToOptions()
        if self._conf.lowBandwidth:
            self._pm.enableLowBandwidth(poeQuality=self._conf.args.poeQuality)
        self._cap = cv2.VideoCapture(self._conf.args.video) if not self._conf.useCamera else None
        self._fps = FPSHandler() if self._conf.useCamera else FPSHandler(self._cap)
        irDrivers = self._device.getIrDrivers()
        irSetFromCmdLine = any([self._conf.args.irDotBrightness, self._conf.args.irFloodBrightness])
        if irDrivers:
            print('IR drivers found on OAK-D Pro:', [f'{d[0]} on bus {d[1]}' for d in irDrivers])
            if not irSetFromCmdLine: print(' --> Go to the `Depth` tab to enable!')
        elif irSetFromCmdLine:
            print('[ERROR] IR drivers not detected on device!')

        if self._conf.useCamera:
            pvClass = SyncedPreviewManager if self._conf.args.sync else PreviewManager
            self._pv = pvClass(display=self._conf.args.show, nnSource=self._conf.getModelSource(), colorMap=self._conf.getColorMap(),
                               dispMultiplier=self._conf.dispMultiplier, mouseTracker=True, decode=self._conf.lowBandwidth and not self._conf.lowCapabilities,
                               fpsHandler=self._fps, createWindows=self._displayFrames, depthConfig=self._pm._depthConfig)

            if self._conf.leftCameraEnabled:
                self._pm.createLeftCam(self._monoRes, self._conf.args.monoFps,
                                 orientation=self._conf.args.cameraOrientation.get(Previews.left.name),
                                 xout=Previews.left.name in self._conf.args.show)
            if self._conf.rightCameraEnabled:
                self._pm.createRightCam(self._monoRes, self._conf.args.monoFps,
                                  orientation=self._conf.args.cameraOrientation.get(Previews.right.name),
                                  xout=Previews.right.name in self._conf.args.show)
            if self._conf.rgbCameraEnabled:
                self._pm.createColorCam(previewSize=self._conf.previewSize, res=self._rgbRes, fps=self._conf.args.rgbFps,
                                  orientation=self._conf.args.cameraOrientation.get(Previews.color.name),
                                  fullFov=not self._conf.args.disableFullFovNn,
                                  xout=Previews.color.name in self._conf.args.show)

            if self._conf.useDepth:
                self._pm.createDepth(self._conf.args.disparityConfidenceThreshold,
                                     self._conf.getMedianFilter(),
                                     self._conf.args.sigma,
                                     self._conf.args.stereoLrCheck,
                                     self._conf.args.lrcThreshold,
                                     self._conf.args.extendedDisparity,
                                     self._conf.args.subpixel,
                                     useDepth=Previews.depth.name in self._conf.args.show or Previews.depthRaw.name in self._conf.args.show,
                                     useDisparity=Previews.disparity.name in self._conf.args.show or Previews.disparityColor.name in self._conf.args.show,
                                     useRectifiedLeft=Previews.rectifiedLeft.name in self._conf.args.show,
                                     useRectifiedRight=Previews.rectifiedRight.name in self._conf.args.show,
                                     alignment=dai.CameraBoardSocket.RGB if self._conf.args.stereoLrCheck and not self._conf.args.noRgbDepthAlign else None)

            if self._conf.irEnabled(self._device):
                self._pm.updateIrConfig(self._device, self._conf.args.irDotBrightness, self._conf.args.irFloodBrightness)

            self._encManager = None
            if len(self._conf.args.encode) > 0:
                self._encManager = EncodingManager(self._conf.args.encode, self._conf.args.encodeOutput)
                self._encManager.createEncoders(self._pm)

        if len(self._conf.args.report) > 0:
            self._pm.createSystemLogger()

        if self._conf.useNN:
            self._nn = self._nnManager.createNN(
                pipeline=self._pm.pipeline, nodes=self._pm.nodes, source=self._conf.getModelSource(),
                blobPath=self._blobManager.getBlob(shaves=self._conf.shaves, openvinoVersion=self._nnManager.openvinoVersion),
                useDepth=self._conf.useDepth, minDepth=self._conf.args.minDepth, maxDepth=self._conf.args.maxDepth,
                sbbScaleFactor=self._conf.args.sbbScaleFactor, fullFov=not self._conf.args.disableFullFovNn,
            )

            self._pm.addNn(nn=self._nn, xoutNnInput=Previews.nnInput.name in self._conf.args.show,
                           xoutSbb=self._conf.args.spatialBoundingBox and self._conf.useDepth)
    def run(self):
        self._device.startPipeline(self._pm.pipeline)
        self._pm.createDefaultQueues(self._device)
        if self._conf.useNN:
            self._nnManager.createQueues(self._device)

        self._sbbOut = self._device.getOutputQueue("sbb", maxSize=1, blocking=False) if self._conf.useNN and self._conf.args.spatialBoundingBox else None
        self._logOut = self._device.getOutputQueue("systemLogger", maxSize=30, blocking=False) if len(self._conf.args.report) > 0 else None

        if self._conf.useDepth:
            self._medianFilters = cycle([item for name, item in vars(dai.MedianFilter).items() if name.startswith('KERNEL_') or name.startswith('MEDIAN_')])
            for medFilter in self._medianFilters:
                # move the cycle to the current median filter
                if medFilter == self._pm._depthConfig.postProcessing.median:
                    break
        else:
            self._medianFilters = []

        if self._conf.useCamera:
            cameras = self._device.getConnectedCameras()
            if dai.CameraBoardSocket.LEFT in cameras and dai.CameraBoardSocket.RIGHT in cameras:
                self._pv.collectCalibData(self._device)

            self._updateCameraConfigs({
                "exposure": self._conf.args.cameraExposure,
                "sensitivity": self._conf.args.cameraSensitivity,
                "saturation": self._conf.args.cameraSaturation,
                "contrast": self._conf.args.cameraContrast,
                "brightness": self._conf.args.cameraBrightness,
                "sharpness": self._conf.args.cameraSharpness
            })

            self._pv.createQueues(self._device, self._createQueueCallback)
            if self._encManager is not None:
                self._encManager.createDefaultQueues(self._device)

        self._seqNum = 0
        self._hostFrame = None
        self._sbbRois = []
        self.onSetup(self)

        try:
            while self.shouldRun() and self.canRun():
                self._fps.nextIter()
                self.onIter(self)
                self.loop()
        except StopIteration:
            pass
        except Exception as ex:
            if sentryEnabled:
                from sentry_sdk import capture_exception
                capture_exception(ex)
            raise
        finally:
            self.stop()

    def stop(self, *args, **kwargs):
        if hasattr(self, "_device"):
            print("Stopping demo...")
            self._device.close()
            del self._device
            self._fps.printStatus()
        self._pm.closeDefaultQueues()
        if self._conf.useCamera:
            self._pv.closeQueues()
            if self._encManager is not None:
                self._encManager.close()
        if self._nnManager is not None:
            self._nnManager.closeQueues()
        if self._sbbOut is not None:
            self._sbbOut.close()
        if self._logOut is not None:
            self._logOut.close()
        self.onTeardown(self)

    def canRun(self):
        return hasattr(self, "_device") and not self._device.isClosed()

    def _logMonitorCallback(self, msg):
        if msg.level == dai.LogLevel.CRITICAL:
            print(f"[CRITICAL] [{msg.time.get()}] {msg.payload}", file=sys.stderr)
            sys.stderr.flush()
            temperature = self._device.getChipTemperature()
            if any(map(lambda field: getattr(temperature, field) > 100, ["average", "css", "dss", "mss", "upa"])):
                self.error = OverheatError(msg.payload)
            else:
                self.error = RuntimeError(msg.payload)

    timer = time.monotonic()

    def loop(self):
        global x_global
        global y_global
        global z_global
        diff = time.monotonic() - self.timer
        if diff < 0.02:
            time.sleep(diff)
        self.timer = time.monotonic()

        if self.error is not None:
            self.stop()
            raise self.error

        if self._conf.useCamera:
            self._pv.prepareFrames(callback=self.onNewFrame)
            if self._encManager is not None:
                self._encManager.parseQueues()

            if self._sbbOut is not None:
                sbb = self._sbbOut.tryGet()
                if sbb is not None:
                    self._sbbRois = sbb.getConfigData()
                depthFrames = [self._pv.get(Previews.depthRaw.name), self._pv.get(Previews.depth.name)]
                for depthFrame in depthFrames:
                    if depthFrame is None:
                        continue

                    for roiData in self._sbbRois:
                        roi = roiData.roi.denormalize(depthFrame.shape[1], depthFrame.shape[0])
                        topLeft = roi.topLeft()
                        bottomRight = roi.bottomRight()
                        # Display SBB on the disparity map
                        cv2.rectangle(depthFrame, (int(topLeft.x), int(topLeft.y)), (int(bottomRight.x), int(bottomRight.y)), self._nnManager._bboxColors[0], 2)
        else:
            readCorrectly, rawHostFrame = self._cap.read()
            if not readCorrectly:
                raise StopIteration()

            self._nnManager.sendInputFrame(rawHostFrame, self._seqNum)
            self._seqNum += 1
            self._hostFrame = rawHostFrame
            self._fps.tick('host')

        if self._nnManager is not None:
            inNn = self._nnManager.parse()
            if inNn is not None:
                self.onNn(inNn)
                self._fps.tick('nn')

        if self._conf.useCamera:
            if self._nnManager is not None:
                x_global, y_global, z_global = self._nnManager.draw(self._pv)
                #send_data(x_global, y_global, z_global)
                ready_to_send = True
            self._pv.showFrames(callback=self._showFramesCallback)
        elif self._hostFrame is not None:
            debugHostFrame = self._hostFrame.copy()
            if self._nnManager is not None:
                x_global, y_global, z_global = self._nnManager.draw(debugHostFrame)
                #send_data(x_global, y_global, z_global)
                ready_to_send = True
            self._fps.drawFps(debugHostFrame, "host")
            if self._displayFrames:
                cv2.imshow("host", debugHostFrame)

        if self._logOut:
            logs = self._logOut.tryGetAll()
            for log in logs:
                self._printSysInfo(log)

        if self._displayFrames:
            key = cv2.waitKey(1)
            if key == ord('q'):
                raise StopIteration()
            elif key == ord('m'):
                nextFilter = next(self._medianFilters)
                self._pm.updateDepthConfig(self._device, median=nextFilter)

            if self._conf.args.cameraControlls:
                update = True

                if key == ord('t'):
                    self._cameraConfig["exposure"] = 10000 if self._cameraConfig["exposure"] is None else 500 if self._cameraConfig["exposure"] == 1 else min(self._cameraConfig["exposure"] + 500, 33000)
                    if self._cameraConfig["sensitivity"] is None:
                        self._cameraConfig["sensitivity"] = 800
                elif key == ord('g'):
                    self._cameraConfig["exposure"] = 10000 if self._cameraConfig["exposure"] is None else max(self._cameraConfig["exposure"] - 500, 1)
                    if self._cameraConfig["sensitivity"] is None:
                        self._cameraConfig["sensitivity"] = 800
                elif key == ord('y'):
                    self._cameraConfig["sensitivity"] = 800 if self._cameraConfig["sensitivity"] is None else min(self._cameraConfig["sensitivity"] + 50, 1600)
                    if self._cameraConfig["exposure"] is None:
                        self._cameraConfig["exposure"] = 10000
                elif key == ord('h'):
                    self._cameraConfig["sensitivity"] = 800 if self._cameraConfig["sensitivity"] is None else max(self._cameraConfig["sensitivity"] - 50, 100)
                    if self._cameraConfig["exposure"] is None:
                        self._cameraConfig["exposure"] = 10000
                elif key == ord('u'):
                    self._cameraConfig["saturation"] = 0 if self._cameraConfig["saturation"] is None else min(self._cameraConfig["saturation"] + 1, 10)
                elif key == ord('j'):
                    self._cameraConfig["saturation"] = 0 if self._cameraConfig["saturation"] is None else max(self._cameraConfig["saturation"] - 1, -10)
                elif key == ord('i'):
                    self._cameraConfig["contrast"] = 0 if self._cameraConfig["contrast"] is None else min(self._cameraConfig["contrast"] + 1, 10)
                elif key == ord('k'):
                    self._cameraConfig["contrast"] = 0 if self._cameraConfig["contrast"] is None else max(self._cameraConfig["contrast"] - 1, -10)
                elif key == ord('o'):
                    self._cameraConfig["brightness"] = 0 if self._cameraConfig["brightness"] is None else min(self._cameraConfig["brightness"] + 1, 10)
                elif key == ord('l'):
                    self._cameraConfig["brightness"] = 0 if self._cameraConfig["brightness"] is None else max(self._cameraConfig["brightness"] - 1, -10)
                elif key == ord('p'):
                    self._cameraConfig["sharpness"] = 0 if self._cameraConfig["sharpness"] is None else min(self._cameraConfig["sharpness"] + 1, 4)
                elif key == ord(';'):
                    self._cameraConfig["sharpness"] = 0 if self._cameraConfig["sharpness"] is None else max(self._cameraConfig["sharpness"] - 1, 0)
                else:
                    update = False

                if update:
                    self._updateCameraConfigs()

    def _createQueueCallback(self, queueName):
        if self._displayFrames and queueName in [Previews.disparityColor.name, Previews.disparity.name, Previews.depth.name, Previews.depthRaw.name]:
            Trackbars.createTrackbar('Disparity confidence', queueName, self.DISP_CONF_MIN, self.DISP_CONF_MAX, self._conf.args.disparityConfidenceThreshold,
                     lambda value: self._pm.updateDepthConfig(dct=value))
            if queueName in [Previews.depthRaw.name, Previews.depth.name]:
                Trackbars.createTrackbar('Bilateral sigma', queueName, self.SIGMA_MIN, self.SIGMA_MAX, self._conf.args.sigma,
                         lambda value: self._pm.updateDepthConfig(sigma=value))
            if self._conf.args.stereoLrCheck:
                Trackbars.createTrackbar('LR-check threshold', queueName, self.LRCT_MIN, self.LRCT_MAX, self._conf.args.lrcThreshold,
                         lambda value: self._pm.updateDepthConfig(lrcThreshold=value))
            if self._device.getIrDrivers():
                Trackbars.createTrackbar('IR Laser Dot Projector [mA]', queueName, 0, 1200, self._conf.args.irDotBrightness,
                         lambda value: self._device.setIrLaserDotProjectorBrightness(value))
                Trackbars.createTrackbar('IR Flood Illuminator [mA]', queueName, 0, 1500, self._conf.args.irFloodBrightness,
                         lambda value: self._device.setIrFloodLightBrightness(value))

    def _updateCameraConfigs(self, config):
        parsedConfig = {}
        for configOption, values in config.items():
            if values is not None:
                for cameraName, value in values:
                    newConfig = {
                        **parsedConfig.get(cameraName, {}),
                        configOption: value
                    }
                    if cameraName == "all":
                        parsedConfig[Previews.left.name] = newConfig
                        parsedConfig[Previews.right.name] = newConfig
                        parsedConfig[Previews.color.name] = newConfig
                    else:
                        parsedConfig[cameraName] = newConfig

        if self._conf.leftCameraEnabled and Previews.left.name in parsedConfig:
            self._pm.updateLeftCamConfig(**parsedConfig[Previews.left.name])
        if self._conf.rightCameraEnabled and Previews.right.name in parsedConfig:
            self._pm.updateRightCamConfig(**parsedConfig[Previews.right.name])
        if self._conf.rgbCameraEnabled and Previews.color.name in parsedConfig:
            self._pm.updateColorCamConfig(**parsedConfig[Previews.color.name])

    def _showFramesCallback(self, frame, name):
        returnFrame = self.onShowFrame(frame, name)
        return returnFrame if returnFrame is not None else frame


    def _printSysInfo(self, info):
        m = 1024 * 1024 # MiB
        if not hasattr(self, "_reportFile"):
            if "memory" in self._conf.args.report:
                print(f"Drr used / total - {info.ddrMemoryUsage.used / m:.2f} / {info.ddrMemoryUsage.total / m:.2f} MiB")
                print(f"Cmx used / total - {info.cmxMemoryUsage.used / m:.2f} / {info.cmxMemoryUsage.total / m:.2f} MiB")
                print(f"LeonCss heap used / total - {info.leonCssMemoryUsage.used / m:.2f} / {info.leonCssMemoryUsage.total / m:.2f} MiB")
                print(f"LeonMss heap used / total - {info.leonMssMemoryUsage.used / m:.2f} / {info.leonMssMemoryUsage.total / m:.2f} MiB")
            if "temp" in self._conf.args.report:
                t = info.chipTemperature
                print(f"Chip temperature - average: {t.average:.2f}, css: {t.css:.2f}, mss: {t.mss:.2f}, upa0: {t.upa:.2f}, upa1: {t.dss:.2f}")
            if "cpu" in self._conf.args.report:
                print(f"Cpu usage - Leon OS: {info.leonCssCpuUsage.average * 100:.2f}%, Leon RT: {info.leonMssCpuUsage.average * 100:.2f} %")
            print("----------------------------------------")
        else:
            data = {}
            if "memory" in self._conf.args.report:
                data = {
                    **data,
                    "ddrUsed": info.ddrMemoryUsage.used,
                    "ddrTotal": info.ddrMemoryUsage.total,
                    "cmxUsed": info.cmxMemoryUsage.used,
                    "cmxTotal": info.cmxMemoryUsage.total,
                    "leonCssUsed": info.leonCssMemoryUsage.used,
                    "leonCssTotal": info.leonCssMemoryUsage.total,
                    "leonMssUsed": info.leonMssMemoryUsage.used,
                    "leonMssTotal": info.leonMssMemoryUsage.total,
                }
            if "temp" in self._conf.args.report:
                data = {
                    **data,
                    "tempAvg": info.chipTemperature.average,
                    "tempCss": info.chipTemperature.css,
                    "tempMss": info.chipTemperature.mss,
                    "tempUpa0": info.chipTemperature.upa,
                    "tempUpa1": info.chipTemperature.dss,
                }
            if "cpu" in self._conf.args.report:
                data = {
                    **data,
                    "cpuCssAvg": info.leonCssCpuUsage.average,
                    "cpuMssAvg": info.leonMssCpuUsage.average,
                }

            if self._reportFile.tell() == 0:
                print(','.join(data.keys()), file=self._reportFile)
            self.onReport(data)
            print(','.join(map(str, data.values())), file=self._reportFile)