/* Synthetic stand-in for a parse file, written for the sbgecom2pack tests. */
SbgErrorCode sbgEComLogEkfNavReadFromStream(SbgEComLogDemoNav *pLogData, SbgStreamBuffer *pStreamBuffer)
{
    bool        shouldContinue;

    assert(pLogData);
    assert(pStreamBuffer);

    pLogData->timeStamp     = sbgStreamBufferReadUint32LE(pStreamBuffer);
    pLogData->velocity[0]   = sbgStreamBufferReadFloatLE(pStreamBuffer);
    pLogData->velocity[1]   = sbgStreamBufferReadFloatLE(pStreamBuffer);
    pLogData->velocity[2]   = sbgStreamBufferReadFloatLE(pStreamBuffer);
    pLogData->position[0]   = sbgStreamBufferReadDoubleLE(pStreamBuffer);
    pLogData->position[1]   = sbgStreamBufferReadDoubleLE(pStreamBuffer);
    pLogData->position[2]   = sbgStreamBufferReadDoubleLE(pStreamBuffer);
    pLogData->undulation    = sbgStreamBufferReadFloatLE(pStreamBuffer);
    pLogData->status        = (SbgDemoStatus)sbgStreamBufferReadUint16LE(pStreamBuffer);

    if (sbgStreamBufferGetSpace(pStreamBuffer) >= sizeof(uint8_t))
    {
        pLogData->quality   = sbgStreamBufferReadInt8LE(pStreamBuffer);
        shouldContinue = true;
    }
    else
    {
        pLogData->quality   = INT8_MAX;
        shouldContinue = false;
    }

    return sbgStreamBufferGetLastError(pStreamBuffer);
}

SbgErrorCode sbgEComLogDemoExtraReadFromStream(SbgEComLogDemoExtra *pLogData, SbgStreamBuffer *pStreamBuffer)
{
    pLogData->timeStamp = sbgStreamBufferReadUint32LE(pStreamBuffer);
    return sbgStreamBufferReadBuffer(pStreamBuffer, pLogData->blob, sizeof(pLogData->blob));
}

SbgErrorCode sbgEComLogDemoLoopReadFromStream(SbgEComLogDemoLoop *pLogData, SbgStreamBuffer *pStreamBuffer)
{
    pLogData->count = sbgStreamBufferReadUint8(pStreamBuffer);
    for (size_t i = 0; i < pLogData->count; i++)
    {
        pLogData->values[i] = sbgStreamBufferReadUint16LE(pStreamBuffer);
    }
    return sbgStreamBufferGetLastError(pStreamBuffer);
}

SbgErrorCode sbgEComLogDemoFastReadFromStream(SbgEComLogDemoFast *pLogData, SbgStreamBuffer *pStreamBuffer)
{
    pLogData->timeStamp = sbgStreamBufferReadUint32LE(pStreamBuffer);
    pLogData->accel     = (float)sbgStreamBufferReadInt16LE(pStreamBuffer) * 0.01f;
    return sbgStreamBufferGetLastError(pStreamBuffer);
}
