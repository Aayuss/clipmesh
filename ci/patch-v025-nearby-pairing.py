from pathlib import Path
import os, platform, re, shutil

root=Path(__file__).resolve().parents[1]; project=root/'clipmesh'; system=os.environ.get('CLIPMESH_PLATFORM',platform.system())

def replace(path,old,new,label,count=1):
    text=path.read_text(encoding='utf-8'); found=text.count(old)
    if found!=count: raise SystemExit(f'{label}: expected {count} match in {path}, found {found}')
    path.write_text(text.replace(old,new,count),encoding='utf-8')

if system=='Darwin':
    app=root/'ci/ClipMeshApp.swift'; transfer=root/'ci/ClipMeshTransfer.swift'; build=project/'scripts/build-macos.sh'
    replace(transfer,'    func isFavorite(_ fingerprint: String) -> Bool { TransferPrefs.favorites.contains(fingerprint) }','    var fingerprint: String { TransferPrefs.fingerprint }\n\n    func isFavorite(_ fingerprint: String) -> Bool { TransferPrefs.favorites.contains(fingerprint) }','mac fingerprint exposure')
    replace(app,'    private var transferDeviceStack: NSStackView!','    private var transferDeviceStack: NSStackView!\n    private var nearbyPairStack: NSStackView!','mac nearby pair property')
    replace(app,'        LocalTransferManager.shared.start(aliasProvider: { [weak self] in\n            self?.latestState?.deviceName ?? Runtime.deviceName()\n        })',r'''        LocalTransferManager.shared.start(aliasProvider: { [weak self] in
            self?.latestState?.deviceName ?? Runtime.deviceName()
        })
        let nearbyPair = NearbyPairingManager.shared
        nearbyPair.aliasProvider = { [weak self] in self?.latestState?.deviceName ?? Runtime.deviceName() }
        nearbyPair.fingerprintProvider = { LocalTransferManager.shared.fingerprint }
        nearbyPair.approvalPrompt = { [weak self] sender in self?.approveNearbyPair(sender) ?? false }
        nearbyPair.codePrompt = { [weak self] sender, submit in self?.promptNearbyCode(sender, submit: submit) }
        nearbyPair.credentialConsumer = { [weak self] uri, sender in self?.acceptNearbyCredential(uri, sender: sender) ?? false }
        nearbyPair.start()''','mac pairing startup')
    replace(app,'        LocalTransferManager.shared.stop()\n        stopDaemon()','        NearbyPairingManager.shared.stop()\n        LocalTransferManager.shared.stop()\n        stopDaemon()','mac pairing shutdown',2)
    anchor='''        let peers = glassCard(); let peersHeader = NSStackView(); peersHeader.orientation = .horizontal; peersHeader.alignment = .centerY; peersHeader.addArrangedSubview(sectionLabel("PAIRED DEVICES")); peersHeader.addArrangedSubview(spacer()); peersHeader.addArrangedSubview(closureButton("Refresh", primary: false) { [weak self] in self?.refreshHome() }); peers.addArrangedSubview(peersHeader); peersHeader.widthAnchor.constraint(equalTo: peers.widthAnchor, constant: -36).isActive = true; peersStack = NSStackView(); peersStack.orientation = .vertical; peersStack.alignment = .leading; peersStack.spacing = 8; peers.addArrangedSubview(peersStack); peersStack.widthAnchor.constraint(equalTo: peers.widthAnchor, constant: -36).isActive = true; stack.addArrangedSubview(peers); peers.widthAnchor.constraint(equalTo: stack.widthAnchor, constant: -60).isActive = true
'''
    replace(app,anchor,anchor+'''        let nearby = glassCard(); let nearbyHeader = NSStackView(); nearbyHeader.orientation = .horizontal; nearbyHeader.alignment = .centerY; nearbyHeader.addArrangedSubview(sectionLabel("AVAILABLE NEARBY DEVICES")); nearbyHeader.addArrangedSubview(spacer()); nearbyHeader.addArrangedSubview(closureButton("Rescan", primary: false) { LocalTransferManager.shared.discoverNow(); self.refreshNearbyPairDevices() }); nearby.addArrangedSubview(nearbyHeader); nearbyHeader.widthAnchor.constraint(equalTo: nearby.widthAnchor, constant: -36).isActive = true; nearbyPairStack = NSStackView(); nearbyPairStack.orientation = .vertical; nearbyPairStack.alignment = .leading; nearbyPairStack.spacing = 9; nearby.addArrangedSubview(nearbyPairStack); nearbyPairStack.widthAnchor.constraint(equalTo: nearby.widthAnchor, constant: -36).isActive = true; stack.addArrangedSubview(nearby); nearby.widthAnchor.constraint(equalTo: stack.widthAnchor, constant: -60).isActive = true
''','mac nearby clipboard card')
    replace(app,'        if index == 1 { startTransferTimer() } else { transferTimer?.invalidate(); transferTimer = nil }','        if index == 0 || index == 1 { startTransferTimer() } else { transferTimer?.invalidate(); transferTimer = nil }\n        if index == 0 { LocalTransferManager.shared.discoverNow(); refreshNearbyPairDevices() }','mac clipboard discovery timer')
    replace(app,'        if latestState != nil { refreshHome() }\n    }\n\n    private func hideWindow() {\n        window?.orderOut(nil)','        if latestState != nil { refreshHome() }\n        if selectedTab == 0 || selectedTab == 1 { startTransferTimer() }\n    }\n\n    private func hideWindow() {\n        transferTimer?.invalidate(); transferTimer = nil\n        window?.orderOut(nil)','mac suspend hidden UI timer')
    replace(app,'    private func startTransferTimer() { transferTimer?.invalidate(); transferTimer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in self?.refreshTransferDevices() }; refreshTransferDevices() }',r'''    private func startTransferTimer() { transferTimer?.invalidate(); transferTimer = Timer.scheduledTimer(withTimeInterval: 2.0, repeats: true) { [weak self] _ in guard let self else { return }; if self.selectedTab == 0 { self.refreshNearbyPairDevices() } else if self.selectedTab == 1 { self.refreshTransferDevices() } }; if selectedTab == 0 { refreshNearbyPairDevices() } else { refreshTransferDevices() } }
    private func refreshNearbyPairDevices() {
        guard nearbyPairStack != nil else { return }; nearbyPairStack.arrangedSubviews.forEach { nearbyPairStack.removeArrangedSubview($0); $0.removeFromSuperview() }; let devices=LocalTransferManager.shared.nearbyDevices()
        if devices.isEmpty { let e=NSTextField(labelWithString:"No unpaired ClipMesh devices visible on this network.");e.textColor = .secondaryLabelColor;nearbyPairStack.addArrangedSubview(e);return }
        for d in devices { let row=NSStackView();row.orientation = .horizontal;row.alignment = .centerY;row.spacing=10;let name=NSTextField(labelWithString:d.alias);name.font = .systemFont(ofSize:15,weight:.semibold);row.addArrangedSubview(name);row.addArrangedSubview(spacer());row.addArrangedSubview(closureButton("Pair",primary:true){[weak self] in self?.startNearbyPair(d)});nearbyPairStack.addArrangedSubview(row);row.widthAnchor.constraint(equalTo:nearbyPairStack.widthAnchor).isActive=true }
    }
    private func startNearbyPair(_ device: TransferDevice) {
        do { let credential=try Runtime.pairingLink(); statusLabel.stringValue="Waiting for \(device.alias)…"; NearbyPairingManager.shared.pair(credential:credential,with:device,code:{ value in let alert=NSAlert();alert.messageText="Verification code";alert.informativeText="Type this code on \(device.alias):\n\n\(value)";alert.addButton(withTitle:"Keep pairing");alert.runModal() },completion:{[weak self] result in switch result { case .success: self?.statusLabel.stringValue="Paired with \(device.alias)";self?.refreshHome();case .failure(let error):self?.showError(error.localizedDescription) }}) } catch { showError(error.localizedDescription) }
    }
    private func approveNearbyPair(_ sender:String)->Bool { var accepted=false;let work={let alert=NSAlert();alert.messageText="Clipboard pairing request";alert.informativeText="\(sender) wants to pair with this Mac for encrypted clipboard sync.";alert.addButton(withTitle:"Accept");alert.addButton(withTitle:"Reject");NSApp.activate(ignoringOtherApps:true);accepted=alert.runModal() == .alertFirstButtonReturn};if Thread.isMainThread{work()}else{DispatchQueue.main.sync(execute:work)};return accepted }
    private func promptNearbyCode(_ sender:String,submit:@escaping(String?)->Void){DispatchQueue.main.async{let alert=NSAlert();alert.messageText="Verify \(sender)";alert.informativeText="Type the six-digit code shown on \(sender).";alert.addButton(withTitle:"Pair");alert.addButton(withTitle:"Cancel");let input=NSTextField(string:"");input.placeholderString="6-digit code";input.frame=NSRect(x:0,y:0,width:260,height:26);alert.accessoryView=input;submit(alert.runModal() == .alertFirstButtonReturn ? input.stringValue:nil)}}
    private func acceptNearbyCredential(_ uri:String,sender:String)->Bool { var ok=false;let work={self.stopDaemon();do{try Runtime.join(uri,name:self.latestState?.deviceName ?? Runtime.deviceName());try self.startDaemon();self.refreshHome();ok=true}catch{try? self.startDaemon();self.showError(error.localizedDescription)}};if Thread.isMainThread{work()}else{DispatchQueue.main.sync(execute:work)};return ok }''','mac nearby pairing methods')
    replace(app,'            renderPeers(state.peers)','            renderPeers(state.peers)\n            if selectedTab == 0 { refreshNearbyPairDevices() }','mac nearby refresh')
    replace(build,'"$MAIN_SRC" "$TRANSFER_SRC"','"$MAIN_SRC" "$TRANSFER_SRC" "../ci/ClipMeshNearbyPairing.swift"','mac compile pairing source')
    replace(build,'0.2.4','0.2.5','mac package version',4)

elif system=='Windows':
    ui=root/'ci/ClipMeshWindows.cs'; transfer=root/'ci/ClipMeshTransfer.cs'; build=project/'scripts/build-windows.ps1'
    replace(ui,'private const string Version = "0.2.4";','private const string Version = "0.2.5";','windows version')
    replace(ui,'    private readonly FlowLayoutPanel peersPanel;','    private readonly FlowLayoutPanel peersPanel;\n    private readonly FlowLayoutPanel nearbyPairPanel;','windows nearby property')
    anchor='''        Panel peersCard = MakeCard(170); peersCard.Width = 650; Label peersCaption = MakeLabel("PAIRED DEVICES", 8, FontStyle.Bold, Muted); peersCaption.SetBounds(18, 15, 300, 20); Button refresh = MakeButton("Refresh", false); refresh.SetBounds(536, 10, 95, 38); refresh.Click += delegate { RefreshHome(); }; peersPanel = new FlowLayoutPanel(); peersPanel.FlowDirection = FlowDirection.TopDown; peersPanel.WrapContents = false; peersPanel.AutoSize = false; peersPanel.SetBounds(18, 50, 613, 102); peersPanel.BackColor = Card; peersCard.Controls.Add(peersCaption); peersCard.Controls.Add(refresh); peersCard.Controls.Add(peersPanel); flow.Controls.Add(peersCard); Panel pairAction = MakeCard(72); pairAction.Width = 650; Button pairNew = MakeButton("Pair new device", true); pairNew.SetBounds(18, 14, 180, 42); pairNew.Click += delegate { SwitchTab(2); pairInput.Focus(); }; pairAction.Controls.Add(pairNew); flow.Controls.Add(pairAction);
'''
    replace(ui,anchor,anchor+'''        Panel nearbyPairCard=MakeCard(205);nearbyPairCard.Width=650;Label nearbyPairTitle=MakeLabel("AVAILABLE NEARBY DEVICES",8,FontStyle.Bold,Muted);nearbyPairTitle.SetBounds(18,15,320,20);Button pairRescan=MakeButton("Rescan",false);pairRescan.SetBounds(536,10,95,38);pairRescan.Click+=delegate{LocalTransferManagerC.Shared.DiscoverNow();RefreshNearbyPairDevices();};nearbyPairPanel=new FlowLayoutPanel();nearbyPairPanel.FlowDirection=FlowDirection.TopDown;nearbyPairPanel.WrapContents=false;nearbyPairPanel.AutoScroll=true;nearbyPairPanel.SetBounds(18,52,613,132);nearbyPairPanel.BackColor=Card;nearbyPairCard.Controls.Add(nearbyPairTitle);nearbyPairCard.Controls.Add(pairRescan);nearbyPairCard.Controls.Add(nearbyPairPanel);flow.Controls.Add(nearbyPairCard);
''','windows nearby clipboard card')
    replace(ui,'transferTimer = new System.Windows.Forms.Timer(); transferTimer.Interval = 1500; transferTimer.Tick += delegate { if (selectedTab == 1) RefreshTransferDevices(); };','transferTimer = new System.Windows.Forms.Timer(); transferTimer.Interval = 2000; transferTimer.Tick += delegate { if (selectedTab == 0) RefreshNearbyPairDevices(); else if (selectedTab == 1) RefreshTransferDevices(); };','windows low-power visible timer')
    replace(ui,'        transferTimer.Enabled = index == 1;','        transferTimer.Enabled = index == 0 || index == 1;','windows clipboard timer')
    replace(ui,'    private void HideToTray()\n    {\n        Hide();','    private void HideToTray()\n    {\n        transferTimer.Enabled = false;\n        Hide();','windows suspend hidden UI timer')
    replace(ui,'        Activate();\n        if (latestState != null) RefreshHome();','        Activate();\n        transferTimer.Enabled = selectedTab == 0 || selectedTab == 1;\n        if (latestState != null) RefreshHome();','windows restore visible UI timer')
    replace(ui,'        if (index == 0) { RefreshClipboardPreview(); if (latestState != null) RefreshHome(); }','        if (index == 0) { LocalTransferManagerC.Shared.DiscoverNow(); RefreshNearbyPairDevices(); if (latestState != null) RefreshHome(); }','windows clipboard discovery')
    replace(ui,'                LocalTransferManagerC.Shared.IncomingPrompt = AskIncomingFiles;\n                LocalTransferManagerC.Shared.Start(transferState.DeviceName);',r'''                LocalTransferManagerC.Shared.IncomingPrompt = AskIncomingFiles;
                LocalTransferManagerC.Shared.Start(transferState.DeviceName);
                NearbyPairingManagerC.Shared.AliasProvider=delegate{return latestState==null?transferState.DeviceName:latestState.DeviceName;};
                NearbyPairingManagerC.Shared.FingerprintProvider=delegate{return LocalTransferManagerC.Shared.Fingerprint;};
                NearbyPairingManagerC.Shared.ApprovalPrompt=ApproveNearbyPair;
                NearbyPairingManagerC.Shared.CodePrompt=PromptNearbyCode;
                NearbyPairingManagerC.Shared.CredentialConsumer=AcceptNearbyCredential;
                NearbyPairingManagerC.Shared.Start();''','windows pairing startup')
    replace(ui,'        LocalTransferManagerC.Shared.Stop();\n        StopDaemon();','        NearbyPairingManagerC.Shared.Stop();\n        LocalTransferManagerC.Shared.Stop();\n        StopDaemon();','windows pairing shutdown')
    replace(ui,'            RenderPeers(state.Peers);','            RenderPeers(state.Peers);\n            if (selectedTab == 0) RefreshNearbyPairDevices();','windows nearby refresh')
    insert=r'''    private void RefreshNearbyPairDevices(){if(nearbyPairPanel==null||nearbyPairPanel.IsDisposed)return;nearbyPairPanel.Controls.Clear();List<TransferDeviceC> devices=LocalTransferManagerC.Shared.Nearby();if(devices.Count==0){Label empty=MakeLabel("No unpaired ClipMesh devices visible on this network.",9,FontStyle.Regular,Muted);empty.Width=560;empty.Height=38;nearbyPairPanel.Controls.Add(empty);return;}foreach(TransferDeviceC d in devices){Panel row=new Panel();row.Width=570;row.Height=48;row.BackColor=Card;Label name=MakeLabel(d.Alias,10,FontStyle.Bold,Ink);name.SetBounds(4,12,380,24);Button pair=MakeButton("Pair",true);pair.SetBounds(456,5,108,38);pair.Click+=delegate{StartNearbyPair(d);};row.Controls.Add(name);row.Controls.Add(pair);nearbyPairPanel.Controls.Add(row);}}
    private void StartNearbyPair(TransferDeviceC device){string credential;try{credential=ClipMeshRuntime.PairingLink();}catch(Exception ex){ShowError(ex.Message);return;}status.Text="Waiting for "+device.Alias+"…";Task.Run(delegate{try{NearbyPairingManagerC.Shared.Pair(credential,device,delegate(string value){if(!IsDisposed)BeginInvoke((Action)(delegate{MessageBox.Show(this,"Type this code on "+device.Alias+":\r\n\r\n"+value,"Verification code",MessageBoxButtons.OK,MessageBoxIcon.Information);}));});if(!IsDisposed)BeginInvoke((Action)(delegate{status.Text="Paired with "+device.Alias;RefreshHome();}));}catch(Exception ex){if(!IsDisposed)BeginInvoke((Action)(delegate{ShowError(ex.Message);}));}});}
    private bool ApproveNearbyPair(string sender){bool accepted=false;MethodInvoker work=delegate{RestoreFromTray();accepted=MessageBox.Show(this,sender+" wants to pair with this PC for encrypted clipboard sync.","Clipboard pairing request",MessageBoxButtons.YesNo,MessageBoxIcon.Information)==DialogResult.Yes;};if(InvokeRequired)Invoke(work);else work();return accepted;}
    private void PromptNearbyCode(string sender,Action<string> submit){MethodInvoker work=delegate{string value=Prompt("Verify "+sender,"Type the six-digit code shown on "+sender+".","");submit(value);};if(InvokeRequired)BeginInvoke(work);else work();}
    private bool AcceptNearbyCredential(string uri,string sender){bool ok=false;MethodInvoker work=delegate{StopDaemon();try{ClipMeshRuntime.JoinSpace(uri,latestState==null?Environment.MachineName:latestState.DeviceName);StartDaemon();RefreshHome();ok=true;}catch(Exception ex){try{StartDaemon();}catch{}ShowError(ex.Message);}};if(InvokeRequired)Invoke(work);else work();return ok;}

'''
    replace(ui,'    private void RefreshTransferDevices()\n    {',insert+'    private void RefreshTransferDevices()\n    {','windows nearby methods')
    replace(build,"$transferSource = Join-Path $PSScriptRoot '..\\..\\ci\\ClipMeshTransfer.cs'","$transferSource = Join-Path $PSScriptRoot '..\\..\\ci\\ClipMeshTransfer.cs'\n$pairingSource = Join-Path $PSScriptRoot '..\\..\\ci\\ClipMeshNearbyPairing.cs'",'windows pairing source')
    replace(build,'    $transferSource','    $transferSource `\n    $pairingSource','windows compile pairing source')

elif system=='Linux':
    java=project/'android/app/src/main/java/dev/clipmesh'; main=java/'MainActivity.kt'; share=java/'fileshare/FileShareActivity.kt'; settings=java/'SettingsActivity.kt'; engine=java/'fileshare/LocalTransferEngine.kt'; gradle=project/'android/app/build.gradle.kts'
    shutil.copyfile(root/'ci/NearbyPairingManager.kt',java/'fileshare/NearbyPairingManager.kt');shutil.copyfile(root/'ci/NearbyPairingUi.kt',java/'fileshare/NearbyPairingUi.kt')
    replace(gradle,'versionCode = 14','versionCode = 15','android version code')
    replace(gradle,'versionName = "0.2.4"','versionName = "0.2.5"','android version name')
    replace(engine,'        executor.execute(::runAnnouncer)','        executor.execute(::runAnnouncer)\n        NearbyPairingManager.start(context)','android pairing startup')
    replace(engine,'        nearby.clear()','        NearbyPairingManager.stop()\n        nearby.clear()','android pairing shutdown')
    replace(main,'import dev.clipmesh.fileshare.IncomingRequestUi','import dev.clipmesh.fileshare.IncomingRequestUi\nimport dev.clipmesh.fileshare.NearbyPairingManager\nimport dev.clipmesh.fileshare.NearbyPairingUi','android pairing imports')
    replace(main,'    private lateinit var peersContainer: LinearLayout','    private lateinit var peersContainer: LinearLayout\n    private lateinit var nearbyPairContainer: LinearLayout','android nearby property')
    replace(main,'        IncomingRequestUi.attach(this)','        IncomingRequestUi.attach(this)\n        NearbyPairingUi.attach(this)','android pairing attach')
    replace(main,'    override fun onPause() { IncomingRequestUi.detach(this); if (!settings.receiveFilesInBackground) LocalTransferEngine.stop(); super.onPause() }','    override fun onPause() { IncomingRequestUi.detach(this); NearbyPairingUi.detach(this); if (!settings.receiveFilesInBackground) LocalTransferEngine.stop(); super.onPause() }','android pairing detach')
    anchor='''        peersCard.addView(peersContainer)

        root.addView(button("Pair new device") {'''
    replace(main,anchor,'''        peersCard.addView(peersContainer)

        val nearbyCard=card(root)
        val nearbyHeader=LinearLayout(this).apply{orientation=LinearLayout.HORIZONTAL;gravity=Gravity.CENTER_VERTICAL}
        nearbyHeader.addView(label("AVAILABLE NEARBY DEVICES",11f,true,muted).apply{letterSpacing=.12f},LinearLayout.LayoutParams(0,ViewGroup.LayoutParams.WRAP_CONTENT,1f))
        nearbyHeader.addView(button("Rescan",false){LocalTransferEngine.discoverNow();nearbyHeader.postDelayed({renderNearbyPairDevices()},450)},LinearLayout.LayoutParams(dp(92),dp(42)))
        nearbyCard.addView(nearbyHeader)
        nearbyPairContainer=LinearLayout(this).apply{orientation=LinearLayout.VERTICAL;setPadding(0,dp(8),0,0)}
        nearbyCard.addView(nearbyPairContainer)

        root.addView(button("Pair new device") {''','android nearby clipboard card')
    replace(main,'        renderPeers()','        renderPeers()\n        renderNearbyPairDevices()','android nearby render')
    insert=r'''    private fun renderNearbyPairDevices(){if(!::nearbyPairContainer.isInitialized)return;nearbyPairContainer.removeAllViews();val devices=LocalTransferEngine.nearbyDevices();if(devices.isEmpty()){nearbyPairContainer.addView(label("No unpaired ClipMesh devices visible on this network.",14f,false,muted));return};devices.forEach{device->val row=LinearLayout(this).apply{orientation=LinearLayout.HORIZONTAL;gravity=Gravity.CENTER_VERTICAL};row.addView(label(device.alias,16f,true,ink),LinearLayout.LayoutParams(0,ViewGroup.LayoutParams.WRAP_CONTENT,1f));row.addView(button("Pair"){startNearbyPair(device)},LinearLayout.LayoutParams(dp(96),dp(44)));nearbyPairContainer.addView(row)}}
    private fun startNearbyPair(device:LocalTransferEngine.TransferDevice){val space=settings.spaceId?:run{toast("Create or join a clipboard space first");return};val key=secrets.loadSpaceKey()?:run{toast("Clipboard key is unavailable");return};val credential=Pairing.toUri(Pairing.PairingData(space,key,settings.deviceName,settings.deviceId));status.text="Waiting for ${device.alias}…";NearbyPairingManager.pairClipboard(this,device,credential,{value->runOnUiThread{AlertDialog.Builder(this).setTitle("Verification code").setMessage("Type this code on ${device.alias}:\n\n$value").setPositiveButton("Keep pairing",null).show()}},{result->runOnUiThread{result.fold({status.text="Paired with ${device.alias}";refreshHome()},{toast(it.message?:"Pairing failed")})}})}

'''
    replace(main,'    private fun renderPeers() {',insert+'    private fun renderPeers() {','android nearby methods')
    for path in (share,settings):
        replace(path,'import dev.clipmesh.fileshare.IncomingRequestUi','import dev.clipmesh.fileshare.IncomingRequestUi\nimport dev.clipmesh.fileshare.NearbyPairingUi',f'android pairing UI import {path.name}') if path==settings else None
    replace(share,'    override fun onResume() { super.onResume(); IncomingRequestUi.attach(this); LocalTransferEngine.start(this); LocalTransferEngine.discoverNow() }','    override fun onResume() { super.onResume(); IncomingRequestUi.attach(this); NearbyPairingUi.attach(this); LocalTransferEngine.start(this); LocalTransferEngine.discoverNow() }','android file pairing attach')
    replace(share,'    override fun onPause() { IncomingRequestUi.detach(this); if (!dev.clipmesh.SettingsStore(this).receiveFilesInBackground) LocalTransferEngine.stop(); super.onPause() }','    override fun onPause() { IncomingRequestUi.detach(this); NearbyPairingUi.detach(this); if (!dev.clipmesh.SettingsStore(this).receiveFilesInBackground) LocalTransferEngine.stop(); super.onPause() }','android file pairing detach')
    replace(settings,'        IncomingRequestUi.attach(this)','        IncomingRequestUi.attach(this)\n        NearbyPairingUi.attach(this)','android settings pairing attach')
    replace(settings,'        IncomingRequestUi.detach(this)','        IncomingRequestUi.detach(this)\n        NearbyPairingUi.detach(this)','android settings pairing detach')
else: raise SystemExit(f'unsupported platform {system}')

print(f'Applied ClipMesh v0.2.5 authenticated nearby clipboard pairing on {system}')
