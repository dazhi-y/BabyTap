import Foundation
import Speech

let resultURL = CommandLine.arguments.count >= 3
    ? URL(fileURLWithPath: CommandLine.arguments[2])
    : nil

func emit(_ payload: [String: Any], code: Int32 = 0) -> Never {
    let data = try! JSONSerialization.data(withJSONObject: payload)
    if let resultURL = resultURL {
        try? data.write(to: resultURL, options: .atomic)
    } else {
        FileHandle.standardOutput.write(data)
        FileHandle.standardOutput.write(Data("\n".utf8))
    }
    exit(code)
}

guard CommandLine.arguments.count == 2 || CommandLine.arguments.count == 3 else {
    emit(["error": "缺少音频文件"], code: 2)
}

let audioURL = URL(fileURLWithPath: CommandLine.arguments[1])
guard let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "zh-CN")),
      recognizer.isAvailable else {
    emit(["error": "macOS 中文语音识别当前不可用"], code: 3)
}

func transcribe() {
    let request = SFSpeechURLRecognitionRequest(url: audioURL)
    request.shouldReportPartialResults = false
    if recognizer.supportsOnDeviceRecognition {
        request.requiresOnDeviceRecognition = true
    }
    recognizer.recognitionTask(with: request) { result, error in
        if let result = result, result.isFinal {
            let transcription = result.bestTranscription
            let segments = transcription.segments
            let totalDuration = segments.reduce(0.0) { total, segment in
                total + max(segment.duration, 0.05)
            }
            let confidence = totalDuration > 0
                ? segments.reduce(0.0) { total, segment in
                    total + Double(segment.confidence) * max(segment.duration, 0.05)
                } / totalDuration
                : 0.0
            emit([
                "transcript": transcription.formattedString,
                "confidence": confidence,
            ])
        }
        if let error = error {
            emit(["error": error.localizedDescription], code: 4)
        }
    }
}

switch SFSpeechRecognizer.authorizationStatus() {
case .authorized:
    transcribe()
case .notDetermined:
    SFSpeechRecognizer.requestAuthorization { status in
        if status == .authorized {
            transcribe()
        } else {
            emit(["error": "未获得 macOS 语音识别权限"], code: 5)
        }
    }
default:
    emit(["error": "macOS 语音识别权限已关闭"], code: 5)
}

RunLoop.main.run()
