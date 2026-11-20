/* Synthetic stand-in for sbgEComLog.c, written for the sbgecom2pack tests. */
SbgErrorCode sbgEComLogParse(SbgEComClass msgClass, SbgEComMsgId msgId, const void *pPayload, size_t payloadSize, SbgEComLogUnion *pLogData)
{
    if (msgClass == SBG_ECOM_CLASS_LOG_ECOM_0)
    {
        switch (msgId)
        {
        case SBG_ECOM_LOG_NAV:
            errorCode = sbgEComLogEkfNavReadFromStream(&pLogData->nav, &inputStream);
            break;
        case SBG_ECOM_LOG_EXTRA:
            errorCode = sbgEComLogDemoExtraReadFromStream(&pLogData->extra, &inputStream);
            break;
        case SBG_ECOM_LOG_LOOPED:
            errorCode = sbgEComLogDemoLoopReadFromStream(&pLogData->loop, &inputStream);
            break;
        }
    }
    else if (msgClass == SBG_ECOM_CLASS_LOG_ECOM_1)
    {
        switch ((SbgEComLog1)msgId)
        {
        case SBG_ECOM_LOG_FAST:
            errorCode = sbgEComLogDemoFastReadFromStream(&pLogData->fast, &inputStream);
            break;
        }
    }
}
